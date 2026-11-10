from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import camera, config, recognizer, session


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {message}", flush=True)


@dataclass
class Decision:
    state: str
    distance: float | None
    action: str | None
    reason: str


class Guard:
    def __init__(self, cfg: config.Config, dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.rec = recognizer.Recognizer(cfg.verify.threshold)
        self.rec.load()
        self.absent_since: float | None = None
        self.impostor_streak = 0
        self._episode_locked = False

    def evaluate_once(self) -> Decision:
        cfg = self.cfg
        frame = camera.grab_frame(
            cfg.camera.device, cfg.camera.width, cfg.camera.height, cfg.camera.warmup_frames
        )
        face = camera.largest_face(frame)

        if face is None:
            self.impostor_streak = 0
            now = time.monotonic()
            if self.absent_since is None:
                self.absent_since = now
                return Decision("absent", None, None, "no face detected")
            gone = (now - self.absent_since) / 60.0
            if gone >= cfg.verify.absent_grace_minutes and not self._episode_locked:
                return self._lock(
                    f"nobody at the desk for {gone:.1f} min "
                    f"(grace {cfg.verify.absent_grace_minutes} min)",
                    "absent",
                    None,
                )
            return Decision("absent", None, None, f"absent {gone:.1f} min")

        self.absent_since = None
        result = self._verify_burst()

        if result.matched:
            self.impostor_streak = 0
            self._episode_locked = False
            return Decision(
                "present",
                result.distance,
                None,
                f"distance {result.distance:.1f} <= {result.threshold:.1f}",
            )

        self.impostor_streak += 1
        if self._episode_locked:
            return Decision(
                "impostor",
                result.distance,
                None,
                f"already locked for this episode; distance {result.distance:.1f}",
            )
        if self.impostor_streak >= cfg.verify.impostor_checks:
            return self._lock(
                f"face did not match for {self.impostor_streak} consecutive checks "
                f"(distance {result.distance:.1f} > {result.threshold:.1f})",
                "impostor",
                result.distance,
            )
        return Decision(
            "impostor?",
            result.distance,
            None,
            f"distance {result.distance:.1f} > {result.threshold:.1f}, "
            f"streak {self.impostor_streak}/{cfg.verify.impostor_checks}",
        )

    def _verify_burst(self) -> recognizer.Result:
        """Match against several frames and take the best score.

        One frame is a lottery: motion blur and blinks push a genuine match
        well past the threshold. Measured on this machine, single-frame
        distances for the same person spread 15.7 while the minimum of six
        spreads 4.8.
        """
        samples = max(1, self.cfg.verify.frames)
        cap = camera.open_camera(
            self.cfg.camera.device,
            self.cfg.camera.width,
            self.cfg.camera.height,
            self.cfg.camera.warmup_frames,
        )
        best: recognizer.Result | None = None
        try:
            taken = 0
            while taken < samples:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                face = camera.largest_face(frame)
                if face is None:
                    continue
                taken += 1
                result = self.rec.predict(face.gray)
                if best is None or result.distance < best.distance:
                    best = result
        finally:
            cap.release()
        if best is None:
            # No frame yielded a face; report an unmatched result rather than
            # inventing a distance, so callers treat this as "not verified".
            return recognizer.Result(matched=False, distance=float("inf"), threshold=self.rec.threshold, label=-1)
        return best

    def _lock(self, reason: str, state: str, distance: float | None) -> Decision:
        self._episode_locked = True
        if self.dry_run:
            log(f"DRY-RUN would lock: {reason}")
            return Decision(state, distance, "would-lock", reason)
        if self.cfg.guard.skip_when_locked and session.is_locked():
            return Decision(state, distance, None, f"{reason}; already locked")
        detail = session.lock()
        log(f"LOCKED: {reason} ({detail})")
        self.absent_since = None
        self.impostor_streak = 0
        return Decision(state, distance, "locked", reason)

    def watch(self) -> None:
        interval = self.cfg.guard.interval_seconds
        log(
            f"guard started: device={self.cfg.camera.device} "
            f"interval={interval}s threshold={self.cfg.verify.threshold} "
            f"dry_run={self.dry_run}"
        )
        while True:
            try:
                decision = self.evaluate_once()
                log(f"{decision.state}: {decision.reason}")
            except Exception as exc:  # keep the loop alive; a dead camera must not go silent
                log(f"ERROR: {exc}")
            time.sleep(interval)
