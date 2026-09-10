# Harness Control Flow

Lifecycle for the fulcra-app-starter harness. A single **harness run** processes one
milestone; the Nurse re-triggers runs (cron, manual, etc.) to advance the project.

Roles:

- 🩺 **Nurse** — harness control: health-check, fix attempts, escalation.
- ✍️ **Generator** — writes code for a milestone.
- ⚖️ **Evaluator** — reviews the generated code and returns a verdict.
- 🎛️ **Coordinator** — flow control and milestone state.

```mermaid
flowchart TD
    LoopStart([RUN LOOP START]) --> PrevRun{🩺 Previous harness run completed?}

    PrevRun -->|✅| InnerLoopStart([HARNESS RUN START])
    PrevRun -->|❌| FixRemain{🩺 Fix attempts remain?}

    FixRemain -->|✅| FixAttempt[🩺 Attempt to fix harness and notify user]
    FixRemain -->|❌| Escalate[🩺 Escalate to user]

    FixAttempt --> InnerLoopStart

    subgraph InnerLoop["Harness Run"]
        InnerLoopStart --> FindIncompleteMilestone[🎛️ Find earliest incomplete milestone]
        FindIncompleteMilestone --> HasMilestone{🎛️ Any incomplete milestone?}

        HasMilestone -->|✅| GenerateCode[✍️ Generate code to implement milestone]
        HasMilestone -->|❌| ProjectComplete([PROJECT COMPLETE])

        GenerateCode --> ReviewCode[⚖️ Review generated code]
        ReviewCode --> ReviewPassed{🎛️ Review passed?}

        ReviewPassed -->|✅| MarkComplete[🎛️ Mark milestone as complete]
        ReviewPassed -->|❌| RetriesRemain{🎛️ Retries remain?}

        MarkComplete --> CompleteRun([COMPLETE HARNESS RUN])

        RetriesRemain -->|✅| LeaveIncomplete[🎛️ Leave milestone as incomplete]
        RetriesRemain -->|❌| BreakInnerLoop[🎛️ End run; mark run as incomplete]

        LeaveIncomplete --> CompleteRun
        BreakInnerLoop --> EndRunIncomplete([END RUN — INCOMPLETE])
    end

    Escalate --> BreakLoop([BREAK RUN LOOP])

    subgraph Legend["🔑 Roles"]
        L1[🩺 Nurse - Harness control]
        L2[✍️ Generator - Code generation]
        L3[⚖️ Evaluator - Code review]
        L4[🎛️ Coordinator - Flow control]
    end

    classDef processStyle fill:#e1f5ff,stroke:#0288d1,stroke-width:2px
    classDef decisionStyle fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    classDef doctorStyle fill:#ffe0b2,stroke:#f57c00,stroke-width:2px
    classDef generatorStyle fill:#e0f2f1,stroke:#26a69a,stroke-width:2px
    classDef evaluatorStyle fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    classDef coordinatorStyle fill:#d1c4e9,stroke:#5e35b1,stroke-width:2px
    classDef startCompleteStyle fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    classDef breakStyle fill:#ffcdd2,stroke:#d32f2f,stroke-width:2px

    class PrevRun,FixRemain,FixAttempt,Escalate doctorStyle
    class GenerateCode generatorStyle
    class ReviewCode evaluatorStyle
    class FindIncompleteMilestone,HasMilestone,ReviewPassed,MarkComplete,RetriesRemain,LeaveIncomplete,BreakInnerLoop coordinatorStyle
    class LoopStart,InnerLoopStart,CompleteRun,ProjectComplete startCompleteStyle
    class BreakLoop,EndRunIncomplete breakStyle
    class L1 doctorStyle
    class L2 generatorStyle
    class L3 evaluatorStyle
    class L4 coordinatorStyle

    linkStyle default stroke:#888888,stroke-width:2px
    style InnerLoop fill:#f5f5f5,stroke:#999999
    style Legend fill:#f5f5f5,stroke:#999999
```
