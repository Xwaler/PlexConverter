#!/bin/sh

SESSION="PlexScripts"
SESSIONEXISTS=$(tmux ls | grep $SESSION)

if ["$SESSIONEXISTS" = ""]
then
    tmux new -d -s $SESSION
    tmux set -g mouse on

    tmux send-keys -t $SESSION 'python3 src/fetcher.py' Enter
    tmux split-window -t $SESSION -h
    tmux send-keys -t $SESSION 'python3 src/converter.py' Enter
fi
tmux attach -t $SESSION
