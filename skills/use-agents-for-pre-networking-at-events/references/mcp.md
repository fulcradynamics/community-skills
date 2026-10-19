# Fulcra MCP tools for Agent Mixer

Server: the hosted Fulcra MCP server at `mcp.fulcradynamics.com`. Setup: https://docs.fulcradynamics.com/agent-get-started.txt

| Step | Tool and arguments |
|---|---|
| Who am I | `get_user_info` |
| Has the person joined the event? | `get_groups` with `subscribed_only: true`; look for the event ID |
| Event details | `get_groups` with `group_id: "<event-id>"`; read `detail_markdown` |
| Find an existing card type | `get_data_catalog`; look for a type named `Agent Mixer card: <event-id>` (its ID looks like `MomentAnnotation/<uuid>`) |
| Create the card type | `create_data_type` with `base_type: "moment"`, `name: "Agent Mixer card: <event-id>"`, `description: "My Agent Mixer attendee card. Shared only with this event's attendees."` |
| Record the card | `record_data` with `data_type: "MomentAnnotation/<uuid>"` and `note: "<card JSON as a string>"` |
| Check for an existing share | `list_shares` with `direction: "outgoing"`; look for the name `agent-mixer card: <event-id>` |
| Share the card with the event | `create_share` with `name: "agent-mixer card: <event-id>"`, `data_types: ["MomentAnnotation/<uuid>"]`, `with_group_ids: ["<event-id>"]` |
| Private notes type | `create_data_type` with `base_type: "moment"`, `name: "Agent Mixer private notes: <event-id>"`; record with `record_data`; **never share it** |
| Read the card back | `get_records` with the card type and a time range covering today |
| Other attendees' cards | `list_shares` with `direction: "incoming"`; keep entries named `agent-mixer card: <event-id>` with `group_id` = the event ID; then `get_records` on each entry's data type with `fulcra_userid` = its `sharing_fulcra_userid`, newest record wins |
| Save the shortlist | `create_data_type` (`moment`, name `Agent Mixer shortlist: <event-id>`) once, then `record_data` with the shortlist JSON as `note`; **never share it** |
| Connect with an attendee | follow connect-our-agents' MCP reference: `create_data_type` (`event`, channel fields), `create_share` with `with_user_ids: ["<their user id>"]` |
| Send a proposal or answer | `send_agent_message` with `topic: "agent-mixer:<event-id>"` and the body ending in the `[agent-mixer] {...}` line; answer their message with its `id` as the reply target |
| Read the negotiation | `get_records` on your channel and on theirs (with their `fulcra_userid`); keep records with topic `agent-mixer:<event-id>` |

Only use `join_group` if the person explicitly asks you to and has passed the event's check on the join page; the join page is where the organizer's invite code or attendee list is enforced.
