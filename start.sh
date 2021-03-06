#!/bin/sh

SESSION='PlexConverter'
SESSIONEXISTS=$(tmux ls | grep $SESSION)

if [ "$SESSIONEXISTS" = "" ]; then
  nice -n 19 tmux new -d -s $SESSION
  tmux set -g mouse on

  tmux send-keys -t $SESSION "source venv/bin/activate; python3 src/converter.py" Enter

  tmux split-window -t $SESSION -h
  tmux send-keys -t $SESSION "source venv/bin/activate; python3 src/fetcher.py" Enter

  tmux split-window -t $SESSION -v
  tmux send-keys -t $SESSION "htop -u $USER -d 30" Enter

  tmux select-pane -t $SESSION -L
  tmux split-window -t $SESSION -v
  tmux send-keys -t $SESSION "source venv/bin/activate; python3 src/subtitler.py" Enter

  tmux select-pane -t $SESSION -R
fi
