---
name: fulcra-care-prep
description: Set up, test, and run a recurring care-appointment preparation loop for an individual patient using a calendar connected to Fulcra. Use when a user wants an agent to recognize and track appointment changes, prepare source-attributed pre-visit briefs, capture post-visit debriefs and action items, carry unresolved questions forward, create private shareable summaries, or validate the workflow with mock calendar events before activating it.
---

# Fulcra Care

Create a recurring loop that prepares an individual patient before a care appointment, records what happened afterward, and carries unfinished business into the next visit.

Keep the workflow agent-agnostic. Use the current agent's own scheduled-task capability; do not require a separate scheduler. Treat the workflow as an administrative memory aid, not a source of medical judgment.

## Establish the scope and safety boundary

- Support only the user's own appointments and records in this version. Do not manage care for a child, dependent, family member, or other patient.
- Record only information the user supplies or has authorized the agent to read.
- Do not diagnose, interpret results, recommend treatment, or alter medication instructions.
- Preserve a clinician's interpretation as attributed text rather than adopting it as the agent's conclusion.
- Ask before classifying an ambiguous calendar event as care-related. Do not infer health status from a person's name alone.
- Keep appointment state, briefs, and debriefs private unless the user explicitly approves a specific export or share.

## Check the required capabilities

Before changing anything, confirm that the current environment can:

1. Connect to Fulcra and read the user's connected calendar.
2. Call Fulcra's `get_data_updates` tool to find records added or updated since the previous successful run.
3. Create, read, and update a private Fulcra File.
4. Schedule its own recurring task and run that task without the user's computer remaining open.

If Fulcra is not connected, install and run the official `fulcra-get-started` skill. When skill installation is unavailable, follow `https://docs.fulcradynamics.com/agent-get-started.txt`. Verify one calendar read, one `get_data_updates` call, and one private File write before continuing.

If any capability remains unavailable, stop at that point and tell the user exactly what is missing. Do not claim that the loop is active.

## Ask for the user's preferences

Before reading optional care context, ask the user to choose:

- which Fulcra data sources or Data Types the agent may use;
- the lookback period for those sources;
- a compact or detailed one-screen brief;
- whether to include logistics copied from calendar notes or provider messages;
- whether to create a private clinician-ready File after each brief.

Default to calendar data and information the user enters in this loop when the user does not authorize additional sources. Never expand the selected sources or lookback period silently.

## Create the appointment state

Create a private Fulcra File named `care-appointment-loop.md`. Store:

- the last successful run time or update cursor required by `get_data_updates`;
- the user's selected sources, lookback period, brief preference, and sharing preference;
- confirmed and rejected provider names, locations, title patterns, and corrections;
- each appointment's stable calendar identifier, start and end times, timezone, lifecycle status, brief status, debrief status, and reminder attempts;
- every open item with its type, wording, source, originating appointment, responsible person, due date, status, and last update time;
- whether test mode is active.

Use the stable calendar identifier, not the event title, to prevent duplicate briefs and debrief requests. Attribute each stored item to `user`, `calendar`, `provider document`, `connected source`, or `earlier appointment`; do not merge conflicting sources into an unattributed fact.

## Recognize and maintain appointments

Examine calendar titles, notes, locations, and attendees. Treat explicit terms such as `doctor`, `dentist`, `therapy`, `physical`, `clinic`, `hospital`, `specialist`, or a previously confirmed provider or clinic as evidence.

When the evidence is ambiguous, ask the user whether the event is a care appointment and wait for the answer before including it. Save the confirmed or rejected pattern so the same ambiguity does not prompt repeatedly.

On every calendar change, reconcile by stable identifier:

- update the stored time and timezone when an appointment is rescheduled;
- invalidate an undelivered brief tied to the old time and prepare it for the new time;
- mark a cancelled event as cancelled and suppress its brief, debrief, and reminders;
- merge duplicate representations of the same event only after confirming they refer to one appointment;
- leave past records intact when a future occurrence in a recurring series changes.

## Create the recurring task

Create an hourly task inside the current agent. On every run:

1. Read `care-appointment-loop.md`.
2. Ask Fulcra what was added or updated since the last successful run by calling `get_data_updates`.
3. Reconcile cancellations, reschedules, timezones, duplicates, and user corrections before sending anything.
4. Identify confirmed care appointments beginning within the next 24 hours and appointments that ended within the previous two hours.
5. Run the appropriate pre-visit, post-visit, or missed-debrief action once per stable event identifier.
6. Save the updated appointment state and the new successful-run time only after the run completes.
7. Produce no message when nothing relevant changed, no appointment action is due, and no answer from the user is pending.

If the agent supports event-relative scheduling, it may replace hourly polling with one run about 24 hours before each appointment and another about one hour afterward, but it must repeat the validation below after changing the trigger.

## Prepare the pre-visit brief

For an upcoming appointment without a completed brief, ask the user:

1. What changed since the last relevant visit?
2. What do you want to ask?
3. What must this appointment accomplish?

Classify the appointment only to organize the brief:

- for primary care, emphasize active concerns, changes, prior open items, and the user's questions;
- for a specialist, emphasize the referral reason, relevant prior results as described by their sources, changes since the last visit, and open follow-ups;
- for dental care, emphasize the user's symptoms or concerns, prior work, and questions;
- for therapy or behavioral-health care, include only topics and goals the user explicitly chooses to record;
- for an unknown type, use the general structure without guessing.

Combine the answers with unresolved items and the authorized context window. Return a one-screen brief containing source-attributed changes, prioritized questions, open items, logistics copied from authorized sources, and the desired outcome. Mark the brief complete only after delivering it.

If the user enabled a clinician-ready File, create a private File named `care-appointment-brief-YYYY-MM-DD.md`. Do not share, publish, email, or export it without the user's explicit approval for that specific action and recipient.

## Capture the post-visit debrief and action list

For an appointment that ended within the previous two hours and has no completed debrief, ask for:

- readings or results and how the clinician described them;
- medication changes;
- tests or referrals;
- questions that were not answered;
- the user's observations;
- the next follow-up date;
- actions, responsible people, and due dates stated during the visit.

Record only what the user reports. Convert stated follow-ups into an action list with `action`, `responsible person`, `due date`, `source`, and `status`; do not invent missing instructions, owners, or dates. Preserve missing answers as unresolved items and mark the debrief complete after saving it.

If the user does not respond, leave the debrief pending and ask once more about 24 hours later. After that second request, stop prompting, keep a visible `debrief missing` item, and carry it forward until the user completes or dismisses it.

## Learn from corrections

When the user corrects an appointment classification, provider pattern, source selection, brief length, terminology, or recurring question, save the correction and apply it to later runs. Keep the correction editable and report what changed when asked. Never treat a correction as permission to access a new source or share information.

## Validate with mock appointments

Keep test mode active until every check passes. Run the test rather than explaining it:

1. Ask the user to create `Mock annual physical with Dr. Rowan` 23 hours from now. Run the task, collect the three answers, and produce exactly one general or primary-care brief with source labels.
2. Run again without changes and confirm silence.
3. Reschedule the event by two hours. Confirm that the stored time changes and no reminder fires at the old time.
4. Create a duplicate of the event. Confirm that the agent asks before merging and still produces only one brief.
5. Cancel the duplicate and confirm that no debrief or reminder is produced for it.
6. Create `Planning with Dr. Rowan` without care-related notes. Confirm that the agent asks before classifying it and remembers a rejection.
7. Move the original mock event so it ended 30 minutes ago. Run again, collect a debrief with one unfinished question and one dated action, and confirm both retain their sources.
8. Simulate no response to the debrief. Confirm one later retry and then a `debrief missing` item with no further prompts.
9. Create `Follow-up with Dr. Rowan` 23 hours from now. Confirm that the unresolved question and unfinished action appear once without repeating the first visit.
10. Revoke access to one optional source. Confirm the task names the lost source, continues with authorized context, and does not reuse cached content from the revoked source.
11. Create `Dentist appointment` within the next 24 hours. Leave the recurring task enabled until one automatic run detects it; an on-demand run proves the instructions, while this run proves the schedule.
12. Run once more with no relevant changes and confirm silence.

Return a test report listing each check as `passed`, `failed`, or `blocked`, plus every permission request and deviation from these instructions. Do not activate the real loop or call the skill tested until all checks pass. After the user approves the report, remove the mock records from the state File, turn off test mode, and leave the recurring task enabled.

## Extend the community skill

Keep the base skill independent of any patient portal or electronic health record. A community fork may add a connector, including an Epic/MyChart connector, only when a suitable documented public API is available and the user can grant authorized access.

Require every connector to expose its source name, authorization state, supported record types, update cursor or time boundary, and revocation behavior. Keep connector-specific authentication and field mappings outside the core loop. Degrade cleanly when the connector is unavailable, and preserve the same safety boundary, source attribution, state format, validation checks, and silence condition.

Do not scrape patient portals, reuse browser sessions, or bypass provider controls. Encourage contributors to submit generally useful improvements back to the community skill.
