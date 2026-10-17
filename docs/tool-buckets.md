# Tool buckets

`rules_version` for this file is 2. The buckets are the same as in version 1; version 2 changed model time only (`docs/metrics.md`).

The gallery legend names four groups: shell, files, visual checks, and web. The web tooltip says “web and publishing”. The gallery does not publish the classifier that produced the counts.

The rules on this page are the classifier for our runs. They keep the four column names. Two patterns in the reference chart support the boundaries. They are patterns, not a specification.

- Every Codex row has zero file calls. File work in that harness was likely counted as shell. A shell command stays in shell when the command reads or writes files.
- Shell counts are high, and web counts are low. A download through the shell was likely counted as shell. A shell command stays in shell when the command uses the network.

## What counts as one call

Count one invocation as one call. Count a parallel batch of five reads as five file calls. Count a shell invocation as one shell call when the command line contains several commands.

Count only tools the model invoked. Operator actions after the model stops are outside the count.

## What counts as a failure

A failure is a call the harness or the tool reports as failed. A non-zero shell exit is a failure. A cancelled call is a failure when the export marks it failed. A cancelled call that the export omits is not a call.

A screenshot of a broken page is a successful visual check. The page is broken. The tool call succeeded. Record the broken page in `observations`, not as a failure.

A failure stays inside its bucket. It also increments that bucket’s failure count. The red number is the sum of failures in the four chart buckets.

## Buckets

### shell

The tool runs a command in a terminal.

This includes `curl`, `git`, package installs, compilers, and a Python script that writes files. The command’s effect does not move the call to another bucket.

### files

The tool reads, searches, edits, or writes workspace files, and it does not run a shell.

### visual checks

The tool inspects the rendered atlas. A screenshot, a DOM or accessibility snapshot, and a browser-console read are visual checks. A headless browser check whose result is a view of the page is a visual check.

A dev server command is shell. A source-file read is files.

### web

The tool fetches a page or a search result through a web tool, or it publishes the atlas through a publish tool.

`WebSearch` and `WebFetch` are web. A dedicated deploy or publish tool is web.

`curl` in a shell is shell. `git push` in a shell is shell.

### other

Every other model tool goes here. `TodoWrite`, subagent launches, mode switches, and image generation are other.

List each `other` tool in `by_tool` and in `observations`. An unknown tool name stays in `other` until a later `rules_version` gives it a bucket.

## Name map

Use the purpose rules above when a name is missing from this map.

| Harness tool | Bucket |
| --- | --- |
| `Shell`, `Bash`, `shell`, `local_shell` | shell |
| `Read`, `Write`, `Edit`, `StrReplace`, `Delete`, `EditNotebook`, `Glob`, `Grep` | files |
| `WebSearch`, `WebFetch` | web |
| Browser screenshot, page snapshot, browser console read | visual checks |
| `TodoWrite`, `Task`, `SwitchMode`, `AskQuestion`, `GenerateImage`, `ReadLints` | other |

An MCP tool follows the same purpose rules. Record its full tool name in `by_tool`.

## Example

This example is invented. It shows the classifier. It is not a run.

| Call | Bucket | Failure |
| --- | --- | --- |
| `Shell`: `curl` of the Apur layer, exit 0 | shell | no |
| `Shell`: `python build.py`, and the script writes a file, exit 0 | shell | no |
| `Shell`: `npm test`, exit 1 | shell | yes |
| `Read` of a GeoJSON file | files | no |
| `WebFetch` of a documentation page | web | no |
| Browser screenshot of the map | visual checks | no |
| Browser screenshot of an error page | visual checks | no |
| `TodoWrite` | other | no |

Chart total for this example: 6 calls, 1 failure. `other` shows 1 call under the table.
