import sys
import os
import json
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.narrator import StrategicNarrator

def test_agent_handoff():
    print("Testing Agent Handoff logic...")
    narrator = StrategicNarrator()
    if not narrator.enabled:
        print("narrator not enabled, checking env...")
        return

    niche = "B2B Lead Intelligence"
    mock_competitors = [
        {
            "name": "Apollo",
            "analyses": [{"h1": "The World's Largest B2B Database"}],
            "changes": [
                {
                    "from_ts": "2022-01-01",
                    "to_ts": "2023-01-01",
                    "diffs": {"h1": {"from": "B2B Lead Gen", "to": "Revenue Intelligence Platform"}}
                }
            ]
        }
    ]

    print("Generating agent tasks...")
    tasks = narrator.generate_agent_tasks(niche, mock_competitors)
    print(f"Generated {len(tasks)} tasks.")
    print(json.dumps(tasks, indent=2))
    
    if len(tasks) > 0:
        print("SUCCESS: Agent tasks generated.")
    else:
        print("FAILURE: No tasks generated.")

if __name__ == "__main__":
    test_agent_handoff()
