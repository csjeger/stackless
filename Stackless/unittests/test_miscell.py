# import common

import pickle
import unittest
import stackless
import sys
import traceback
import contextlib

from support import StacklessTestCase, AsTaskletTestCase


def is_soft():
    softswitch = stackless.enable_softswitch(0)
    stackless.enable_softswitch(softswitch)
    return softswitch

def runtask():
    x = 0
    # evoke pickling of an xrange object
    dummy = range(10)
    for ii in range(1000):
        x += 1


class TestWatchdog(StacklessTestCase):

    def lifecycle(self, t):
        # Initial state - unrun
        self.assertTrue(t.alive)
        self.assertTrue(t.scheduled)
        self.assertEqual(t.recursion_depth, 0)
        # allow hard switching
        t.set_ignore_nesting(1)

        softSwitching = stackless.enable_softswitch(0); stackless.enable_softswitch(softSwitching)

        # Run a little
        res = stackless.run(10)
        self.assertEqual(t, res)
        self.assertTrue(t.alive)
        self.assertTrue(t.paused)
        self.assertFalse(t.scheduled)
        self.assertEqual(t.recursion_depth, softSwitching and 1 or 2)

        # Push back onto queue
        t.insert()
        self.assertFalse(t.paused)
        self.assertTrue(t.scheduled)

        # Run to completion
        stackless.run()
        self.assertFalse(t.alive)
        self.assertFalse(t.scheduled)
        self.assertEqual(t.recursion_depth, 0)


    def test_aliveness1(self):
        """ Test flags after being run. """
        t = stackless.tasklet(runtask)()
        self.lifecycle(t)

    def test_aliveness2(self):
        """ Same as 1, but with a pickled unrun tasklet. """
        import pickle
        t = stackless.tasklet(runtask)()
        t_new = pickle.loads(pickle.dumps((t)))
        t.remove()
        t_new.insert()
        self.lifecycle(t_new)

    def test_aliveness3(self):
        """ Same as 1, but with a pickled run(slightly) tasklet. """

        t = stackless.tasklet(runtask)()
        t.set_ignore_nesting(1)

        # Initial state - unrun
        self.assertTrue(t.alive)
        self.assertTrue(t.scheduled)
        self.assertEqual(t.recursion_depth, 0)

        softSwitching = stackless.enable_softswitch(0); stackless.enable_softswitch(softSwitching)

        # Run a little
        res = stackless.run(100)

        self.assertEqual(t, res)
        self.assertTrue(t.alive)
        self.assertTrue(t.paused)
        self.assertFalse(t.scheduled)
        self.assertEqual(t.recursion_depth, softSwitching and 1 or 2)

        # Now save & load
        dumped = pickle.dumps(t)
        t_new = pickle.loads(dumped)

        # Remove and insert & swap names around a bit
        t.remove()
        t = t_new
        del t_new
        t.insert()

        self.assertTrue(t.alive)
        self.assertFalse(t.paused)
        self.assertTrue(t.scheduled)
        self.assertEqual(t.recursion_depth, 1)

        # Run to completion
        if is_soft():
            stackless.run()
        else:
            t.kill()
        self.assertFalse(t.alive)
        self.assertFalse(t.scheduled)
        self.assertEqual(t.recursion_depth, 0)

class TestTaskletSwitching(StacklessTestCase):
    """Test the tasklet's own scheduling methods"""
    def test_raise_exception(self):
        c = stackless.channel()
        def foo():
            self.assertRaises(IndexError, c.receive)
        s = stackless.tasklet(foo)()
        s.run() #necessary, since raise_exception won't automatically run it
        s.raise_exception(IndexError)

    def test_run(self):
        c = stackless.channel()
        flag = [False]
        def foo():
            flag[0] = True
        s = stackless.tasklet(foo)()
        s.run()
        self.assertEqual(flag[0], True)

class TestTaskletThrowBase(object):
    def test_throw_noargs(self):
        c = stackless.channel()
        def foo():
            self.assertRaises(IndexError, c.receive)
        s = stackless.tasklet(foo)()
        s.run() #It needs to have started to run
        self.throw(s, IndexError)
        self.aftercheck(s)

    def test_throw_args(self):
        c = stackless.channel()
        def foo():
            try:
                c.receive()
            except Exception as e:
                self.assertTrue(isinstance(e, IndexError));
                self.assertEqual(e.args, (1,2,3))
        s = stackless.tasklet(foo)()
        s.run() #It needs to have started to run
        self.throw(s, IndexError, (1,2,3))
        self.aftercheck(s)

    def test_throw_inst(self):
        c = stackless.channel()
        def foo():
            try:
                c.receive()
            except Exception as e:
                self.assertTrue(isinstance(e, IndexError));
                self.assertEqual(e.args, (1,2,3))
        s = stackless.tasklet(foo)()
        s.run() #It needs to have started to run
        self.throw(s, IndexError(1,2,3))
        self.aftercheck(s)

    def test_throw_exc_info(self):
        c = stackless.channel()
        def foo():
            try:
                c.receive()
            except Exception as e:
                self.assertTrue(isinstance(e, ZeroDivisionError));
        s = stackless.tasklet(foo)()
        s.run() #It needs to have started to run
        def errfunc():
            1/0
        try:
            errfunc()
        except Exception:
            self.throw(s, *sys.exc_info())
        self.aftercheck(s)

    def test_throw_traceback(self):
        c = stackless.channel()
        def foo():
            try:
                c.receive()
            except Exception as e:
                s = "".join(traceback.format_tb(sys.exc_info()[2]))
                self.assertTrue("errfunc" in s)
        s = stackless.tasklet(foo)()
        s.run() #It needs to have started to run
        def errfunc():
            1/0
        try:
            errfunc()
        except Exception:
            self.throw(s, *sys.exc_info())
        self.aftercheck(s)

    def test_new(self):
        c = stackless.channel()
        def foo():
            try:
                c.receive()
            except Exception as e:
                self.assertTrue(isinstance(e, IndexError))
                raise
        s = stackless.tasklet(foo)()
        self.assertEqual(s.frame, None)
        self.assertTrue(s.alive)
        # Test that the current "unhandled exception behaviour"
        # is invoked for the not-yet-running tasklet.
        def doit():
            self.throw(s, IndexError)
        if not self.pending:
            self.assertRaises(IndexError, doit)
        else:
            doit()
            self.assertRaises(IndexError, stackless.run)

    def test_kill_new(self):
        def t():
            self.assertFalse("should not run this")
        s = stackless.tasklet(t)()

        # Should not do anything
        s.throw(TaskletExit)
        # the tasklet should be dead
        stackless.run()
        self.assertRaisesRegexp(RuntimeError, "dead", s.run)

    def test_dead(self):
        c = stackless.channel()
        def foo():
            c.receive()
        s = stackless.tasklet(foo)()
        s.run()
        c.send(None)
        stackless.run()
        self.assertFalse(s.alive)
        def doit():
            self.throw(s, IndexError)
        self.assertRaises(RuntimeError, doit)

    def test_kill_dead(self):
        c = stackless.channel()
        def foo():
            c.receive()
        s = stackless.tasklet(foo)()
        s.run()
        c.send(None)
        stackless.run()
        self.assertFalse(s.alive)
        def doit():
            self.throw(s, TaskletExit)
        # nothing should happen here.
        doit()

    def test_throw_invalid(self):
        s = stackless.getcurrent()
        def t():
            self.throw(s)
        self.assertRaises(TypeError, t)
        def t():
            self.throw(s, IndexError(1), (1,2,3))
        self.assertRaises(TypeError, t)

class TestTaskletThrowImmediate(StacklessTestCase, TestTaskletThrowBase):
    pending = False
    @classmethod
    def throw(cls, s, *args):
        s.throw(*args, pending=cls.pending)

    def aftercheck(self, s):
        # the tasklet ran immediately
        self.assertFalse(s.alive)

class TestTaskletThrowNonImmediate(TestTaskletThrowImmediate):
    pending = True
    def aftercheck(self, s):
        # After the throw, the tasklet still hasn't run
        self.assertTrue(s.alive)
        s.run()
        self.assertFalse(s.alive)

class TestSwitchTrap(StacklessTestCase):
    class SwitchTrap(object):
        def __enter__(self):
            stackless.switch_trap(1)
        def __exit__(self, exc, val, tb):
            stackless.switch_trap(-1)
    switch_trap = SwitchTrap()

    def test_schedule(self):
        s = stackless.tasklet(lambda:None)()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", stackless.schedule)
        stackless.run()

    def test_schedule_remove(self):
        main = []
        s = stackless.tasklet(lambda:main[0].insert())()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", stackless.schedule_remove)
        main.append(stackless.getcurrent())
        stackless.schedule_remove()

    def test_run(self):
        s = stackless.tasklet(lambda:None)()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", stackless.run)
        stackless.run()

    def test_run_specific(self):
        s = stackless.tasklet(lambda:None)()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", s.run)
        s.run()

    def test_send(self):
        c = stackless.channel()
        s = stackless.tasklet(lambda: c.receive())()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", c.send, None)
        c.send(None)

    def test_send_throw(self):
        c = stackless.channel()
        def f():
            self.assertRaises(NotImplementedError, c.receive)
        s = stackless.tasklet(f)()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", c.send_throw, NotImplementedError)
        c.send_throw(NotImplementedError)

    def test_receive(self):
        c = stackless.channel()
        s = stackless.tasklet(lambda: c.send(1))()
        with self.switch_trap:
            self.assertRaises(RuntimeError, c.receive)
        self.assertEqual(c.receive(), 1)

    def test_receive_throw(self):
        c = stackless.channel()
        s = stackless.tasklet(lambda: c.send_throw(NotImplementedError))()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", c.receive)
        self.assertRaises(NotImplementedError, c.receive)

    def test_raise_exception(self):
        c = stackless.channel()
        def foo():
            self.assertRaises(IndexError, c.receive)
        s = stackless.tasklet(foo)()
        s.run() #necessary, since raise_exception won't automatically run it
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", s.raise_exception, RuntimeError)
        s.raise_exception(IndexError)

    def test_kill(self):
        c = stackless.channel()
        def foo():
            self.assertRaises(TaskletExit, c.receive)
        s = stackless.tasklet(foo)()
        s.run() #necessary, since raise_exception won't automatically run it
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", s.kill)
        s.kill()

    def test_run(self):
        c = stackless.channel()
        def foo():
            pass
        s = stackless.tasklet(foo)()
        with self.switch_trap:
            self.assertRaisesRegex(RuntimeError, "switch_trap", s.run)
        s.run()

class TestKill(StacklessTestCase):
    def test_kill_pending_true(self):
        killed = [False]
        def foo():
            try:
                stackless.schedule()
            except TaskletExit:
                killed[0] = True
                raise
        t = stackless.tasklet(foo)()
        t.run()
        self.assertFalse(killed[0])
        t.kill(pending=True)
        self.assertFalse(killed[0])
        t.run()
        self.assertTrue(killed[0])

    def test_kill_pending_False(self):
        killed = [False]
        def foo():
            try:
                stackless.schedule()
            except TaskletExit:
                killed[0] = True
                raise
        t = stackless.tasklet(foo)()
        t.run()
        self.assertFalse(killed[0])
        t.kill(pending=False)
        self.assertTrue(killed[0])

class TestErrorHandler(StacklessTestCase):
    def setUp(self):
        self.handled = self.ran = 0
        self.handled_tasklet = None

    def test_set(self):
        def foo():
            pass
        self.assertEqual(stackless.set_error_handler(foo), None)
        self.assertEqual(stackless.set_error_handler(None), foo)
        self.assertEqual(stackless.set_error_handler(None), None)

    @contextlib.contextmanager
    def handlerctxt(self, handler):
        old = stackless.set_error_handler(handler)
        try:
            yield()
        finally:
            stackless.set_error_handler(old)

    def handler(self, exc, val, tb):
        self.assertTrue(exc)
        self.handled = 1
        self.handled_tasklet = stackless.getcurrent()

    def borken_handler(self, exc, val, tb):
        self.handled = 1
        raise IndexError("we are the mods")

    def get_handler(self):
        h = stackless.set_error_handler(None)
        stackless.set_error_handler(h)
        return h

    def func(self, handler):
        self.ran = 1
        self.assertEqual(self.get_handler(), handler)
        raise ZeroDivisionError("I am borken")

    def test_handler(self):
        stackless.tasklet(self.func)(self.handler)
        with self.handlerctxt(self.handler):
            stackless.run()
        self.assertTrue(self.ran)
        self.assertTrue(self.handled)

    def test_borken_handler(self):
        stackless.tasklet(self.func)(self.borken_handler)
        with self.handlerctxt(self.borken_handler):
            self.assertRaisesRegexp(IndexError, "mods", stackless.run)
        self.assertTrue(self.ran)
        self.assertTrue(self.handled)

    def test_early_hrow(self):
        "test that we handle errors thrown before the tasklet function runs"
        s = stackless.tasklet(self.func)(self.handler)
        with self.handlerctxt(self.handler):
            s.throw(ZeroDivisionError, "thrown error")
        self.assertFalse(self.ran)
        self.assertTrue(self.handled)

    def test_getcurrent(self):
        # verify that the error handler runs in the context of the exiting tasklet
        s = stackless.tasklet(self.func)(self.handler)
        with self.handlerctxt(self.handler):
            s.throw(ZeroDivisionError, "thrown error")
        self.assertTrue(self.handled_tasklet is s)

        self.handled_tasklet = None
        s = stackless.tasklet(self.func)(self.handler)
        with self.handlerctxt(self.handler):
            s.run()
        self.assertTrue(self.handled_tasklet is s)

    def test_throw_pending(self):
        # make sure that throwing a pending error doesn't immediately throw
        def func(h):
            self.ran = 1
            stackless.schedule()
            self.func(h)
        s = stackless.tasklet(func)(self.handler)
        s.run()
        self.assertTrue(self.ran)
        self.assertFalse(self.handled)
        with self.handlerctxt(self.handler):
            s.throw(ZeroDivisionError, "thrown error", pending=True)
        self.assertEqual(self.handled_tasklet, None)
        with self.handlerctxt(self.handler):
            s.run()
        self.assertEqual(self.handled_tasklet, s)


class TestAtomic(StacklessTestCase):
    """Test the getting and setting of the tasklet's 'atomic' flag, and the
       context manager to set it to True
    """
    def testAtomic(self):
        old = stackless.getcurrent().atomic
        try:
            val = stackless.getcurrent().set_atomic(False)
            self.assertEqual(val, old)
            self.assertEqual(stackless.getcurrent().atomic, False)

            val = stackless.getcurrent().set_atomic(True)
            self.assertEqual(val, False)
            self.assertEqual(stackless.getcurrent().atomic, True)

            val = stackless.getcurrent().set_atomic(True)
            self.assertEqual(val, True)
            self.assertEqual(stackless.getcurrent().atomic, True)

            val = stackless.getcurrent().set_atomic(False)
            self.assertEqual(val, True)
            self.assertEqual(stackless.getcurrent().atomic, False)

        finally:
            stackless.getcurrent().set_atomic(old)
        self.assertEqual(stackless.getcurrent().atomic, old)

    def testAtomicCtxt(self):
        old = stackless.getcurrent().atomic
        stackless.getcurrent().set_atomic(False)
        try:
            with stackless.atomic():
                self.assertTrue(stackless.getcurrent().atomic)
        finally:
            stackless.getcurrent().set_atomic(old)

    def testAtomicNopCtxt(self):
        old = stackless.getcurrent().atomic
        stackless.getcurrent().set_atomic(True)
        try:
            with stackless.atomic():
                self.assertTrue(stackless.getcurrent().atomic)
        finally:
            stackless.getcurrent().set_atomic(old)


class TestSchedule(AsTaskletTestCase):
    def setUp(self):
        super(TestSchedule, self).setUp()
        self.events = []

    def testSchedule(self):
        def foo(previous):
            self.events.append("foo")
            self.assertTrue(previous.scheduled)
        t = stackless.tasklet(foo)(stackless.getcurrent())
        self.assertTrue(t.scheduled)
        stackless.schedule()
        self.assertEqual(self.events, ["foo"])

    def testScheduleRemoveFail(self):
        def foo(previous):
            self.events.append("foo")
            self.assertFalse(previous.scheduled)
            previous.insert()
            self.assertTrue(previous.scheduled)
        t = stackless.tasklet(foo)(stackless.getcurrent())
        stackless.schedule_remove()
        self.assertEqual(self.events, ["foo"])


#///////////////////////////////////////////////////////////////////////////////

if __name__ == '__main__':
    import sys
    if not sys.argv[1:]:
        sys.argv.append('-v')

    unittest.main()
