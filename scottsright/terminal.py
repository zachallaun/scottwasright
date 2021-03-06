"""Terminal Wrapper which renders 2d arrays of characters to terminal"""

import signal
import tty
import sys
import re
import os
import subprocess
import logging

import numpy

import termformat

logging.basicConfig(filename='terminal.log',level=logging.DEBUG)



class Terminal(object):
    """

    Renders 2D arrays of characters

    takes in:
     -2D array to render
     -cursor position
    outputs:
     -number of times scrolled
     -keystrokes to be dealt with so a new array can be returned to display
     -initial position of cursor on the screen

    TODO: when less than whole screen owned, deal with that:
        -render the top of the screen at the first clear row
        -scroll down before rendering as necessary

    """
    def __init__(self, in_stream, out_stream):
        """

        in_stream must respond work with tty.setraw(in_stream), and in_stream.read(1)
        out_stream must respond to out_stream.write('some message')
        """
        #TODO does this actually get the terminal settings we need, or because it's a
        # subshell could it be completely wrong, and no better than hardcoding?
        self.original_stty = subprocess.check_output(['stty', '-g'])

        tty.setraw(in_stream)
        self.in_buffer = []
        self.in_stream = in_stream
        self.out_stream = out_stream
        signal.signal(signal.SIGWINCH, lambda signum, frame: self.window_change_event())
        self.top_usable_row, _ = self.get_screen_position()
        logging.debug('initial top_usable_row: %d' % self.top_usable_row)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.cleanup()

    def render_to_terminal(self, array, cursor_pos=(0,0), farray=None):
        """Renders array to terminal, returns the number of lines
            scrolled offscreen

        If array received is of width too small, render it anyway
        if array received is of width too large, render it anyway
        if array received is of height too small, render it anyway
        if array received is of height too large, render it, scroll down,
            and render the rest of it, then return how much we scrolled down
        """
        #TODO add cool render-on-change caching
        #TODO take a formatting array with same dimensions as array

        if farray is None:
            import termformatconstants
            farray = numpy.zeros((array.shape[0], array.shape[1], 3), dtype=int)
            farray[:, :, 0] = 32
            farray[:, :, 1] = 44
            farray[:, :, 2] = termformatconstants.BOLD

        height, width = self.get_screen_size()
        rows_for_use = range(self.top_usable_row, height + 1)
        shared = min(len(array), len(rows_for_use))
        for row, line, fline in zip(rows_for_use[:shared], array[:shared], farray[:shared]):
            self.set_screen_pos((row, 1))
            self.out_stream.write(termformat.formatted_text(line, fline))
        logging.debug('array: '+repr(array))
        logging.debug('shared: '+repr(shared))
        rest_of_lines = array[shared:]
        rest_of_flines = farray[shared:]
        rest_of_rows = rows_for_use[shared:]
        for row in rest_of_rows: # if array too small
            self.set_screen_pos((row, 1))
            self.erase_line()
        logging.debug('length of rest_of_lines: '+repr(rest_of_lines))
        offscreen_scrolls = 0
        for line, fline in zip(rest_of_lines, rest_of_flines): # if array too big
            logging.debug('sending scroll down message')
            self.out_stream.write("D")
            if self.top_usable_row > 1:
                self.top_usable_row -= 1
            else:
                offscreen_scrolls += 1
            logging.debug('new top_usable_row: %d' % self.top_usable_row)
            self.set_screen_pos((height, 1)) # since scrolling moves the cursor
            self.out_stream.write(termformat.formatted_text(line, fline))

        self.set_screen_pos((cursor_pos[0]-offscreen_scrolls+self.top_usable_row, cursor_pos[1]+1))
        return offscreen_scrolls

    def window_change_event(self):
        raise Exception("Window Change Event")
        #TODO this should be in the same input stream, so we need concurrency?

    def get_char(self):
        if self.in_buffer:
            return self.in_buffer.pop(0)
        else:
            return self.in_stream.read(1)

    QUERY_CURSOR_POSITION = "\x1b[6n"
    def move_cursor_direction(char):
        def func(self, n=1):
            if n: self.out_stream.write("[%d%s" % (n, char))
        return func
    up, down, fwd, back = [move_cursor_direction(char) for char in 'ABCD']
    def erase_rest_of_line(self): self.out_stream.write("[K")
    def erase_line(self): self.out_stream.write("[2K")

    def get_screen_position(self):
        """Returns the terminal (row, column) of the cursor"""
        sys.stdout.write(Terminal.QUERY_CURSOR_POSITION)
        resp = ''
        while True:
            c = self.in_stream.read(1)
            resp += c
            m = re.search('(?P<extra>.*)\x1b\[(?P<row>\\d+);(?P<column>\\d+)R', resp)
            if m:
                row = int(m.groupdict()['row'])
                col = int(m.groupdict()['column'])
                self.in_buffer.extend(list(m.groupdict()['extra']))
                return (row, col)

    def set_screen_pos(self, (row, col)):
        self.out_stream.write("[%d;%dH" % (row, col))

    def get_screen_size(self):
        #TODO generalize get_screen_position code and use it here instead
        orig = self.get_screen_position()
        self.fwd(10000)
        self.down(10000)
        size = self.get_screen_position()
        self.set_screen_pos(orig)
        return size

    def array_from_text(self, msg):
        rows, columns = self.get_screen_size()
        a = numpy.array([[' ' for _ in range(columns)] for _ in range(rows)])
        i = 0
        for c in msg:
            if i >= a.size:
                return a
            elif c in '\r\n':
                i = ((i / columns) + 1) * columns
            else:
                a.flat[i] = c
            i += 1
        for r in reversed(range(rows)):
            if all(a[r] == [' ' for _ in range(columns)]):
                a = a[:r]
        return a

    def cleanup(self):
        self.out_stream.write("D")
        rows, _ = self.get_screen_position()
        for i in range(1000):
            self.erase_line()
            self.down()
        self.set_screen_pos((rows, 1))
        os.system('stty '+self.original_stty)
        self.erase_rest_of_line

def test():
    t = Terminal(sys.stdin, sys.stdout)
    rows, columns = t.get_screen_size()
    while True:
        c = t.get_char()
        if c == "":
            t.cleanup()
            sys.exit()
        elif c == "h":
            a = t.array_from_text("a for small array")
        elif c == "a":
            a = numpy.array([[c] * columns for _ in range(rows)])
        elif c == "s":
            a = numpy.array([[c] * columns for _ in range(rows-1)])
        elif c == "d":
            a = numpy.array([[c] * columns for _ in range(rows+1)])
        elif c == "f":
            a = numpy.array([[c] * columns for _ in range(rows-2)])
        elif c == "q":
            a = numpy.array([[c] * columns for _ in range(1)])
        elif c == "w":
            a = numpy.array([[c] * columns for _ in range(1)])
        elif c == "e":
            a = numpy.array([[c] * columns for _ in range(1)])
        elif c == "":
            [t.out_stream.write('\n') for _ in range(rows)]
            continue
        else:
            a = t.array_from_text("unknown command")
        t.render_to_terminal(a)

def main():
    t = Terminal(sys.stdin, sys.stdout)
    rows, columns = t.get_screen_size()
    import random
    goop = lambda l: [random.choice('aaabcddeeeefghiiijklmnooprssttuv        ') for _ in range(l)]
    a = numpy.array([goop(columns) for _ in range(rows)])
    #for char in inputStream():
    t.render_to_terminal(a)
    while True:
        c = t.get_char()
        if c == "":
            t.cleanup()
            sys.exit()
        t.render_to_terminal(numpy.array([[c] * columns for _ in range(rows)]))

def test_array_from_text():
    t = Terminal(sys.stdin, sys.stdout)
    a = t.array_from_text('\n\nhey there\nyo')
    os.system('reset')
    for line in a:
        print ''.join(line)
    raw_input()

if __name__ == '__main__':
    #test_array_from_text()
    test()
