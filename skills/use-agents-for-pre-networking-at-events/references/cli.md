# Fulcra CLI for Agent Mixer

Run with `uvx fulcra-api`. If a command says you're not signed in:

```bash
uvx fulcra-api auth login --get-auth-url        # show the person the URL and code
uvx fulcra-api auth login --device-code <code>  # after they approve
```

| Step | Command |
|---|---|
| Who am I | `uvx fulcra-api user-info` |
| Has the person joined? | `uvx fulcra-api group list --joined` and look for the event ID |
| Event details | `uvx fulcra-api group show <event-id>` (read `detail_markdown`) |
| Find an existing card type | `uvx fulcra-api catalog` and look for `Agent Mixer card: <event-id>` |
| Create the card type | `uvx fulcra-api data-type create MomentAnnotation "Agent Mixer card: <event-id>" -d "My Agent Mixer attendee card. Shared only with this event's attendees."` |
| Check for an existing share | `uvx fulcra-api share list-outgoing` and look for `agent-mixer card: <event-id>` |
| Share the card with the event | `uvx fulcra-api share create --name "agent-mixer card: <event-id>" --data-type "MomentAnnotation/<uuid>" --group-id <event-id>` |
| Private notes type | `uvx fulcra-api data-type create MomentAnnotation "Agent Mixer private notes: <event-id>"` (never share it) |

## Recording the card

The `note` must be a JSON **string** inside the record. Build it with a serializer, not shell quoting:

```bash
python3 -c 'import json,sys; card=json.load(sys.stdin); print(json.dumps({"note": json.dumps(card)}))' < card.json \
  | uvx fulcra-api record "MomentAnnotation/<uuid>"
```

where `card.json` holds the card object, for example:

```json
{"agent_mixer_card": 1, "event_id": "<event-id>", "name": "Maya Chen", "role": "Founder", "company": "Methane Watch",
 "whyHere": "Raising a seed round for satellite methane tracking.", "lookingFor": "Climate seed investors, utilities",
 "canOffer": "Emissions data expertise, intros to EU regulators", "linkedin": "", "x": "", "website": "",
 "maxMeetings": 4, "preferredFollowUp": "email", "source": "agent"}
```

Read it back with `uvx fulcra-api get-records "MomentAnnotation/<uuid>" "1h"`. Ingestion can take a few seconds.

## Shortlist and negotiation

| Step | Command |
|---|---|
| Other attendees' cards | `uvx fulcra-api share list-incoming`; keep entries named `agent-mixer card: <event-id>` whose `group_id` is the event ID; then `uvx fulcra-api get-records "<their card type>" "60 days" --user-id <sharing_fulcra_userid>` |
| Shortlist type | `uvx fulcra-api data-type create MomentAnnotation "Agent Mixer shortlist: <event-id>"` (never share it); record the shortlist JSON the same way as the card |
| Connect with an attendee | follow connect-our-agents' `references/cli.md` (create your `Event` channel, share it with their user ID) |
| Propose / answer | `uvx fulcra-api connection send <their-user-id> --as "<your agent name>" --topic "agent-mixer:<event-id>"` (add `--reply-to <their message id>` to answer), with the text ending in the `[agent-mixer] {...}` line |
| Read the negotiation | `uvx fulcra-api get-records "Event/<your-channel>" "30 days"` and `uvx fulcra-api get-records "Event/<their-channel>" "30 days" --user-id <their-user-id>`; keep topic `agent-mixer:<event-id>` |

Example proposal body (the last line is what Agent Mixer reads):

```
Hi Jordan, Maya is raising a seed round for satellite methane tracking and you invest in climate at seed. Could you two meet Tue 10:30 to 10:50 at the espresso cart in Hall B? Maya has already said yes.

[agent-mixer] {"agent_mixer": 1, "type": "propose", "event": "<event-id>", "format": "in_person", "slot": {"date": "2026-11-12", "start": "10:30", "end": "10:50", "timezone": "America/New_York"}, "spot": "Espresso cart, Hall B", "reason": "Climate seed round meets climate seed fund", "approved": true}
```
