"""Minimal end-to-end example — zero dependencies, no other F1 library.

Run:  python examples/race_story.py
"""
import json

import f1verse

race = f1verse.load(2026, 12)      # 2026 Dutch Grand Prix
story = race.story()

print(f"{story['event']['name']} — {story['event']['total_laps']} laps")
print("Laps led:", story["laps_led"])
for ev in story["timeline"]:
    print(f"  L{ev['lap']:>2} {ev['title']}")
print("\nTop 5:")
for row in story["results"][:5]:
    print(f"  P{row['position']} {row['abbr']:>3} {row['gap']}")

with open("story.json", "w") as f:
    json.dump(story, f, indent=2)
print("\nsaved story.json")
