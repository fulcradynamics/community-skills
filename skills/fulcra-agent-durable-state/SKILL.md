---
name: fulcra-agent-durable-state
description: "Keep an agent's tooling and working state alive across ephemeral machines by treating the Fulcra File Store as the durable home and local disk as cache: restore on wake, push on change, and never stash a secret in a shared path. Use when an agent's scripts vanish after a container rollback or host reboot, when setting up a new agent that must survive its machine, or when deciding where a credential belongs."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "🗃️" } }
---

# Fulcra Agent Durable State

**Ephemeral compute + durable Fulcra state = agents that survive their machines.**

Cloud agent containers get reclaimed and rolled back. Desktop hosts sleep, reboot, and
disappear. Any agent whose tooling lives only on local disk is one filesystem event away
from amnesia — and worse than losing a script is *silently regaining an old one*: a
rollback can revert a patched loop to the unpatched version, or restore a rotated
credential's stale predecessor, and nothing errors until it misbehaves.

The Fulcra File Store does not share the machine's fate. It is versioned, it survives
containers, and `fulcra-api` auth persists independently of scratch disk. So the pattern is:

> **Local disk is a cache. The store is the truth.**

This skill needs only `fulcra-api` — the standard Fulcra CLI. No coordination engine, no
team bus, no other skill.

## Where to start — the re-entrancy probes

Before touching the stash, probe how far this session already got, and enter at the **first
probe that fails**. Every step below is safely re-runnable: uploads and downloads are
whole-file, last-writer-wins.

| Probe (run in order) | Command | Passes when | If it fails, enter at |
|---|---|---|---|
| Auth usable? | `fulcra-api auth print-access-token >/dev/null && echo AUTH-OK` | prints `AUTH-OK` | `fulcra-api auth login` — browser sign-in. A headless agent that cannot complete it should surface to its operator, not improvise |
| Stash exists? | `fulcra-api file list "$STASH/"` | lists at least one file | **First adoption** — nothing durable yet; push your bundle (*On change*) |
| Local cache complete? | `test -x <local-path>` for each tool the stash lists | every tool you depend on exists locally and is executable | **Restore** (*On wake*) |

All three pass → your tooling is durable and current. Work normally, and push on change.
A freshly rolled-back container typically fails the third probe and enters at Restore.

## The stash convention

Pick one path and keep it stable. Anything you control works; a per-agent path keeps
agents from overwriting each other:

```bash
STASH="/agents/<agent-name>/stash"        # solo agent
# STASH="/team/<team>/agents/<agent>/stash"   # if you share a namespace with other agents
```

```
$STASH/
    manifest.json         # sha256 + size + exec bit per file — you write this
    restore-tooling.sh    # the self-heal entrypoint
    listener-loop.sh      # your scripts, loops, config templates
```

### On wake — restore before improvising

```bash
fulcra-api file download "$STASH/manifest.json" manifest.json
python3 - <<'EOF'
import hashlib, json, os, subprocess, sys
m = json.load(open("manifest.json"))
bad = []
for name, meta in m["files"].items():
    subprocess.run(["fulcra-api","file","download",f"{os.environ['STASH']}/{name}",name], check=True)
    got = hashlib.sha256(open(name,"rb").read()).hexdigest()
    if got != meta["sha256"]:
        bad.append(f"{name}: manifest {meta['sha256'][:12]} != downloaded {got[:12]}")
    elif meta.get("exec"):
        os.chmod(name, 0o755)
if bad:
    sys.exit("CHECKSUM DRIFT — refusing a silently-diverged restore:\n  " + "\n  ".join(bad))
print(f"restored {len(m['files'])} file(s), all checksums matched")
EOF
```

**Checksum drift must exit loud.** A restore that quietly hands you a diverged file is
the failure this skill exists to prevent — it is how a disabled escalation step comes
back armed.

### On change — push immediately

An unstashed fix is a fix a rollback will undo.

```bash
# 1. Run the secrets check below. It is not optional.
# 2. Upload, then refresh the manifest:
fulcra-api file upload ./listener-loop.sh "$STASH/listener-loop.sh"
python3 - <<'EOF'
import hashlib, json, os, subprocess
files = {}
for name in os.environ["STASH_FILES"].split():
    b = open(name,"rb").read()
    files[os.path.basename(name)] = {
        "sha256": hashlib.sha256(b).hexdigest(),
        "size": len(b),
        "exec": os.access(name, os.X_OK),
    }
json.dump({"v": 1, "files": files}, open("manifest.json","w"), indent=1)
EOF
fulcra-api file upload manifest.json "$STASH/manifest.json"
```

Then **verify the write landed** — an upload receipt is an acceptance, not a guarantee:

```bash
fulcra-api file download "$STASH/listener-loop.sh" - | sha256sum
```

### Self-heal first

Keep `restore-tooling.sh` in the stash, and make it the first line of any scheduled job's
missing-file branch. A scheduled task's prompt should say *"restore from the stash"*, not
*"rebuild from memory"* — session memory compacts; the store does not.

## The secrets rule (this is most of the lesson)

**Never put a secret in the stash.** A shared team path is readable by every agent that
shares it — that is the point of a shared path. A token there is a token every agent, and
every prompt-injection that lands on any of them, can read. Even a private path is one
mis-scoped share away from the same problem.

Fail closed:

- **Credentials belong in the harness's environment configuration, the OS keychain, or an
  operator-held channel** — never `*.env` files in the stash, no matter how convenient the
  restore would be.
- **Treat filenames as a first filter.** If it is called `.env`, `*.key`, `*secret*`,
  `*token*`, or holds a known credential prefix (`sk-…`, `ghp_…`, `xoxb-…`, a PEM header),
  it does not get uploaded. When in doubt, it is a secret.
- **Config *templates* with the secret redacted are fine.** The restore path then needs
  only the secret from env config, not the whole file from memory.

A pre-upload guard, since without an engine enforcing it the discipline is yours:

```bash
case "$(basename "$F")" in
  .env|*.env|*.key|*.pem|*secret*|*token*|*credential*)
    echo "REFUSED: $F is secret-shaped" >&2; exit 1;;
esac
grep -qE '(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xoxb-|BEGIN [A-Z ]*PRIVATE KEY)' "$F" \
  && { echo "REFUSED: $F contains credential-shaped content" >&2; exit 1; }
```

Test the guard against a file you *know* is secret-shaped before trusting it. A guard that
has never refused anything has not been shown to work.

The asymmetry is deliberate: **losing a script costs one download; leaking a credential
costs a rotation and an incident.**

## Why this exists

One fleet coordinator running in a rollback-prone cloud container lost its scratch tooling
to filesystem reverts repeatedly — three times in a single day at the worst. Each loss cost
a from-memory rebuild, and two reverts were *silent downgrades*: a listener loop whose
disabled escalation step came back armed, and a credentials file whose rotated-out key came
back looking healthy, where the first symptom would have been a mystery `401` an hour later.

Moving the bundle into a File Store stash turned recovery into one download, made the store
copy the arbiter of which version is current, and kept the rotated token out of shared paths
entirely — it rides in environment configuration instead.

## Boundaries

- **Operational state, not narrative state.** This skill durably stores the scripts and
  config that let you act. What you were *doing* — objective, decisions, next step — is a
  separate concern; keep it in your own notes or a continuity checkpoint.
- **Last-writer-wins.** Two agents pushing the same path will clobber each other. Give each
  agent its own stash path, or coordinate out of band.
- **Not a backup product.** It is a working cache with a durable home, not archival storage
  with retention guarantees.
