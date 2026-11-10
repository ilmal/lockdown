from __future__ import annotations

import argparse
import sys

from . import camera, config, guard, recognizer, remote, session


def _cmd_devices(args: argparse.Namespace) -> int:
    import glob

    nodes = sorted(glob.glob("/dev/video*"))
    if not nodes:
        print("no /dev/video* devices found")
        return 1
    for node in nodes:
        info = camera.probe(node)
        if not info.get("open"):
            print(f"{node}: cannot open")
            continue
        shape = info.get("shape")
        print(f"{node}: frame={info.get('frame')} shape={shape} fps={info.get('fps')}")
    print("\nThe greyscale-only node is usually the IR camera.")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    cfg = config.load()
    frame = camera.grab_frame(
        cfg.camera.device, cfg.camera.width, cfg.camera.height, cfg.camera.warmup_frames
    )
    faces = camera.detect_faces(frame)
    print(f"device {cfg.camera.device}: frame {frame.shape}, {len(faces)} face(s)")
    for face in faces:
        print(f"  box={face.box} area={face.area}")
    if not faces:
        print("no face detected — check lighting, framing, and the chosen device")
        return 2
    return 0


def _cmd_enroll(args: argparse.Namespace) -> int:
    cfg = config.load()
    print(f"enrolling {args.samples} samples from {cfg.camera.device}")
    print("look at the camera; move your head slightly between captures")
    recognizer.enroll_samples(cfg, args.samples)
    path = recognizer.train(cfg)
    print(f"model written to {path}")
    print("now run: presence-guard check --verbose")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    cfg = config.load()
    frame = camera.grab_frame(
        cfg.camera.device, cfg.camera.width, cfg.camera.height, cfg.camera.warmup_frames
    )
    face = camera.largest_face(frame)
    if face is None:
        print("no face detected")
        return 2
    rec = recognizer.Recognizer(cfg.verify.threshold)
    rec.load()
    result = rec.predict(face.gray)
    print(
        f"{result.verdict}: distance={result.distance:.1f} threshold={result.threshold:.1f} "
        f"face_area={face.area}"
    )
    return 0 if result.matched else 1


def _cmd_calibrate(args: argparse.Namespace) -> int:
    cfg = config.load()
    rec = recognizer.Recognizer(cfg.verify.threshold)
    rec.load()
    print("capturing 15 checks; sit normally, then look away for some of them")
    values = []
    for i in range(15):
        try:
            frame = camera.grab_frame(
                cfg.camera.device, cfg.camera.width, cfg.camera.height, cfg.camera.warmup_frames
            )
            face = camera.largest_face(frame)
            if face is None:
                print(f"  {i:2d}: no face")
                continue
            result = rec.predict(face.gray)
            values.append(result.distance)
            print(f"  {i:2d}: distance={result.distance:.1f}")
        except Exception as exc:
            print(f"  {i:2d}: error {exc}")
    if not values:
        print("no usable readings")
        return 1
    values.sort()
    print(
        f"\nmin={values[0]:.1f} median={values[len(values) // 2]:.1f} max={values[-1]:.1f}"
    )
    print("set verify.threshold a little above your max for leniency, or near the median for strictness")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.interval:
        cfg.guard.interval_seconds = args.interval
    guard.Guard(cfg, dry_run=args.dry_run).watch()
    return 0


def _cmd_lock(args: argparse.Namespace) -> int:
    print(session.lock(dry_run=args.dry_run))
    return 0


def _cmd_panic(args: argparse.Namespace) -> int:
    print(session.lock(dry_run=args.dry_run))
    print(session.poweroff(dry_run=args.dry_run))
    return 0


def _cmd_hibernate(args: argparse.Namespace) -> int:
    problems = session.hibernate_preflight()
    if problems:
        print("hibernation is not usable on this machine:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("see docs/hibernate.md", file=sys.stderr)
        return 2
    print(session.lock(dry_run=args.dry_run))
    print(session.hibernate(dry_run=args.dry_run))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    remote.serve(config.load())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="presence-guard", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("devices", help="list camera nodes and their frame shapes")
    p.set_defaults(func=_cmd_devices)

    p = sub.add_parser("probe", help="capture one frame and report detected faces")
    p.set_defaults(func=_cmd_probe)

    p = sub.add_parser("enroll", help="capture samples and train the model")
    p.add_argument("--samples", type=int, default=25)
    p.set_defaults(func=_cmd_enroll)

    p = sub.add_parser("check", help="one verification against the enrolled model")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("calibrate", help="print match distances to tune the threshold")
    p.set_defaults(func=_cmd_calibrate)

    p = sub.add_parser("watch", help="run the presence guard loop")
    p.add_argument("--dry-run", action="store_true", help="never lock, only log")
    p.add_argument("--interval", type=int, help="seconds between checks")
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser("lock", help="lock the current session")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_lock)

    p = sub.add_parser("panic", help="lock, then power off")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_panic)

    p = sub.add_parser("hibernate", help="lock, then hibernate (keeps your session)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_hibernate)

    p = sub.add_parser("serve", help="run the Tailscale-only remote endpoint")
    p.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
