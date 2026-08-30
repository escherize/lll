#!/bin/bash
# Diagnostic for the CI failure "issue page has title" where grep -qF failed to
# find 'Web board issue' in a haystack that provably contains it. Temporary.
needle='Web board issue'
echo "grep path: $(command -v grep)"
echo "grep version: $(grep --version | head -1)"
echo "locale: LANG=$LANG LC_ALL=$LC_ALL"
file_form() { LC_ALL=$1 /usr/bin/grep -qF "$needle" "$(dirname "$0")/hay.html"; echo "file LC_ALL=$1: exit $?"; }
file_form2() { LC_ALL=$1 grep -qF "$needle" "$(dirname "$0")/hay.html"; echo "PATH-grep file LC_ALL=$1: exit $?"; }
pipe_form() { printf '%s' "$(cat "$(dirname "$0")/hay.html")" | LC_ALL=$1 /usr/bin/grep -qF -- "$needle"; echo "pipe LC_ALL=$1: exit $?"; }
file_form C; file_form en_US.UTF-8; file_form2 C; file_form2 en_US.UTF-8
pipe_form C; pipe_form en_US.UTF-8
pipe_nodollar() { LC_ALL=$1 /usr/bin/grep -qF -- "$needle" < <(cat "$(dirname "$0")/hay.html"); echo "process-sub LC_ALL=$1: exit $?"; }
pipe_nodollar C
