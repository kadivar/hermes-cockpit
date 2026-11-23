# Records docs/assets/demo-gate.gif: `cockpit demo gate`, the real command with its real output.
#
# Regenerate from the repository root, with `cockpit` on the PATH and vhs, ttyd, ffmpeg, pv and gifsicle installed:
#   vhs docs/assets/demo-gate.tape
#   gifsicle -O3 --lossy=80 --colors 32 -b docs/assets/demo-gate.gif
# The second command shrinks the recording from about 5 MB to under 2 MB; the README links the shrunk file.
#
# The demo prints its whole story in under two seconds, too fast to read, so the hidden setup below puts the output
# through `pv`, which hands it on at a steady pace. Nothing is edited or left out. The sandbox goes under /tmp so
# the path on screen is short and the same on every machine.

Output docs/assets/demo-gate.gif

Set Shell "bash"
Set Theme "Catppuccin Mocha"
Set FontSize 14
Set Width 1020
Set Height 560
Set Padding 16
Set Framerate 8
Set TypingSpeed 55ms

Hide
Type `export PS1='$ ' TMPDIR=/tmp PYTHONUNBUFFERED=1` Enter
Type `cockpit() { command cockpit "$@" | pv -qL 330; }` Enter
Type `clear` Enter
Show

Sleep 600ms
Type "cockpit demo gate"
Sleep 500ms
Enter

# pv hands the output on at 330 bytes a second, so the timing is fixed: the demo reaches its question after about six
# seconds (vhs's Wait cannot see text that has scrolled off the top, so fixed sleeps are used)
Sleep 8s
Enter

# the rest is about 2,500 bytes, 7.5 seconds at that rate; then the last screen holds
Sleep 8s
Sleep 2500ms
