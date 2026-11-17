"""动效引擎：用 FakeRoot/FakeWidget 驱动真引擎，不需要显示器。"""
import unittest
import tkinter as tk

from signin.ui import fx


class FakeWidget:
    def __init__(self):
        self.props = {}
        self.destroyed = False

    def configure(self, **kw):
        if self.destroyed:
            raise tk.TclError("invalid command name")
        self.props.update(kw)

    def kill(self):
        self.destroyed = True


class FakeRoot:
    def __init__(self):
        self.callbacks = []
        self.now = 0.0

    def after(self, _ms, cb):
        self.callbacks.append(cb)

    def pump(self):
        """手动推进一帧：取时间戳、执行排队的 after 回调。"""
        cb = self.callbacks.pop(0)
        cb()

    def pump_until_idle(self, limit=2000):
        for _ in range(limit):
            if not self.callbacks:
                return
            self.pump()


class FxEngineTest(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.engine = fx.FxEngine(self.root, clock=lambda: self.root.now)

    def test_pulse_changes_color_every_frame(self):
        w = FakeWidget()
        self.engine.pulse(w, "fg", "#000000", "#FFFFFF", period=2.0, pause=0.0)
        self.root.pump()               # 第一帧：t=0 → c1
        self.assertEqual(w.props["fg"], "#000000")
        self.root.now = 1.0
        self.root.pump()               # 半周期 → c2
        self.assertEqual(w.props["fg"], "#FFFFFF")

    def test_transition_finishes_and_deregisters(self):
        w = FakeWidget()
        self.engine.transition(w, "bg", "#000000", "#FFFFFF", ms=100)
        self.root.pump()
        self.root.now += 0.2
        self.root.pump_until_idle()
        self.assertEqual(w.props["bg"], "#FFFFFF")
        self.assertEqual(self.engine._jobs, [])  # 结束后自动注销

    def test_same_key_replaces_old_job(self):
        w1, w2 = FakeWidget(), FakeWidget()
        self.engine.transition(w1, "bg", "#111111", "#222222", ms=50, key="t")
        self.engine.transition(w2, "bg", "#333333", "#444444", ms=50, key="t")
        for _ in range(10):
            if not self.root.callbacks:
                break
            self.root.now += 0.03
            self.root.pump()
        self.assertNotIn("bg", w1.props)   # 旧任务被顶掉，没有写过帧
        self.assertEqual(w2.props["bg"], "#444444")

    def test_cancel_stops_job(self):
        w = FakeWidget()
        self.engine.pulse(w, "bg", "#000000", "#FFFFFF", key="p")
        self.engine.cancel("p")
        self.root.pump_until_idle()
        self.assertEqual(self.engine._jobs, [])

    def test_destroyed_widget_is_silently_dropped(self):
        w = FakeWidget()
        self.engine.pulse(w, "bg", "#000000", "#FFFFFF")
        self.root.pump()
        w.kill()
        self.root.pump_until_idle()
        self.assertEqual(self.engine._jobs, [])  # 不抛错、任务退场

    def test_stop_halves_heartbeat(self):
        w = FakeWidget()
        self.engine.pulse(w, "bg", "#000000", "#FFFFFF")
        self.engine.stop()
        self.assertEqual(self.engine._jobs, [])
        self.root.pump_until_idle()
        self.assertEqual(self.root.callbacks, [])  # 不再排帧

    def test_spinner_updates_text(self):
        w = FakeWidget()
        self.engine.spinner(w, base="读取中", fg="#35B5FF")
        self.root.pump()
        self.assertEqual(w.props["fg"], "#35B5FF")
        text = w.props["text"]
        self.assertTrue(text.startswith("读取中 "))
        self.assertIn(text[-1], fx.SPINNER_FRAMES)

    def test_dots_progression(self):
        w = FakeWidget()
        self.engine.dots(w, base="执行中")
        self.root.pump()
        self.assertEqual(w.props["text"], "执行中●")
        self.root.now = 0.9  # 第 4 帧（0.28s 步进）→ "● ●"
        self.root.pump()
        self.assertEqual(w.props["text"], "执行中● ●")

    def test_sweep_moves_coords(self):
        coords = {}

        class FakeCanvas(FakeWidget):
            def coords(self, item, *xy):
                if xy:
                    coords[item] = xy
                return coords.get(item, ())

        c = FakeCanvas()
        self.engine.sweep(c, "band", x0=0, x1=100, y0=0, y1=3)
        self.root.pump()
        # coords 存的是光带 (左, 上, 右, 下)；验证光带中心
        left, _top, right, _bottom = coords["band"]
        self.assertAlmostEqual((left + right) / 2, 0.0, delta=0.1)
        self.root.now = 1.7  # 半周期 → 中心 ≈50
        self.root.pump()
        left, _top, right, _bottom = coords["band"]
        self.assertAlmostEqual((left + right) / 2, 50.0, delta=1.5)

    def test_add_after_stop_is_noop(self):
        w = FakeWidget()
        self.engine.stop()
        self.engine.pulse(w, "bg", "#000000", "#FFFFFF")
        self.assertEqual(self.engine._jobs, [])


if __name__ == "__main__":
    unittest.main()
