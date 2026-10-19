#!/usr/bin/env bash
# One-time, as root, on EACH Spark:   sudo bash ~/install-ds41.sh
#
# Installs the ds41-{head,worker} units beside the ds4 ones (both stay
# installed; which is enabled decides what serves) and a sudoers rule that
# lets animallya96 start/stop/enable/disable exactly these model units and
# drop the page cache without a password, so the cutover and any rollback
# can be driven from a script instead of a person typing sudo at each step.
# The rule grants nothing else. Remove it with: rm /etc/sudoers.d/anios-model-units
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
H=/home/animallya96
for u in ds41-head ds41-worker; do
  [ -f "$H/$u.service" ] && install -m 644 "$H/$u.service" /etc/systemd/system/$u.service && echo "installed $u.service"
done
systemctl daemon-reload
S=/usr/bin/systemctl
UNITS="ds4-head ds4-worker ds41-head ds41-worker anios-vlm"
{
  echo "# AniOS model units: start/stop/enable/disable without a password (install-ds41.sh, 2026-10-19)"
  for u in $UNITS; do
    for v in start stop restart enable disable "enable --now" "disable --now"; do
      echo "animallya96 ALL=(root) NOPASSWD: $S $v $u"
    done
  done
  echo "animallya96 ALL=(root) NOPASSWD: $S daemon-reload"
  echo "animallya96 ALL=(root) NOPASSWD: /usr/bin/tee /proc/sys/vm/drop_caches"
} > /etc/sudoers.d/anios-model-units
chmod 440 /etc/sudoers.d/anios-model-units
visudo -cf /etc/sudoers.d/anios-model-units
echo "ok: $(hostname)"
