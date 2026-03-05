# commuter: Portable AI Coding Session Transfer

## Problem

Claude Code's Remote Control feature lets you view a session from another device, but the session always runs on the original host machine. If that machine sleeps, loses network, or you want to work with local files on a different machine, you're stuck.

**Goal:** Enable true session migration between machines that share a synced filesystem (via Git, Dropbox, Syncthing, etc.). Export a coding session on Machine A, import it on Machine B, and continue working with full local file access on Machine B.


