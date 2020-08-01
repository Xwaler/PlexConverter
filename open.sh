#!/bin/sh

cd ~/PlexConverter
SESSION='PlexConverter'
SESSIONEXISTS=$(tmux ls | grep $SESSION)

if [ "$SESSIONEXISTS" != "" ]; then
  tmux attach -t $SESSION
fi
