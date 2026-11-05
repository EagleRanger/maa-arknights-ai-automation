"""Navigation-only visual reply to an existing waiting daily controller."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_ai_navigation_v1 import write_navigation_reply


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--event-id', required=True)
    p.add_argument('--screenshot', required=True)
    p.add_argument('--note', required=True)
    a = p.parse_args()
    print(json.dumps(write_navigation_reply(a.output, run_id=a.run_id, event_id=a.event_id,
          screenshot=a.screenshot, note=a.note), ensure_ascii=False))


if __name__ == '__main__':
    main()
