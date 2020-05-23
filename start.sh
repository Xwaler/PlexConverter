#!/bin/sh

SESSION="PlexScripts"
SESSIONEXISTS=$(tmux ls | grep $SESSION)

if [ "$SESSIONEXISTS" = "" ]; then
  tmux new -d -s $SESSION
  tmux set -g mouse on

  tmux send-keys -t $SESSION 'python3 src/converter.py' Enter

  tmux split-window -t $SESSION -h
  tmux send-keys -t $SESSION 'python3 src/fetcher.py' Enter

  tmux split-window -t $SESSION -v
  tmux send-keys -t $SESSION 'top -d 10'

  tmux select-pane -t $SESSION -L
  tmux split-window -t $SESSION -v
  tmux send-keys -t $SESSION 'python3 src/subtitler.py' Enter

  tmux select-pane -t $SESSION -R
fi
tmux attach -t $SESSION
