from __future__ import annotations

from typing import Iterable


def generate_zsh_completion(prog: str = "chrootctl") -> str:
    fn = f"_{prog}"
    commands = "status mount unmount fix-tty doctor logs start restart exec install upgrade completion chroots users"
    distros = "ubuntu arch"
    phases = "extract bootstrap desktop finalize"
    desktops = "xfce4 plasma none"
    profiles = "minimal dev xfce4 plasma custom"
    completion_subcommands = "zsh"
    chroots_subcommands = "list show remove rename"
    users_subcommands = "show-id sync-id"

    return f"""#compdef {prog}

typeset -g {fn}_prog="{prog}"

{fn}_have() {{
  (( $+commands[$1] ))
}}

{fn}_dynamic() {{
  "${{{fn}_prog}}" "$@" 2>/dev/null
}}

{fn}_preview_file() {{
  local target="$1"
  if [[ -d "$target" ]]; then
    if {fn}_have lsd; then
      lsd --color=always "$target" 2>/dev/null
    else
      ls -lah "$target" 2>/dev/null
    fi
    return
  fi
  if {fn}_have bat; then
    bat --style=plain --color=always --line-range=:120 "$target" 2>/dev/null
  else
    sed -n '1,120p' "$target" 2>/dev/null
  fi
}}

{fn}_fzf_pick() {{
  local source_cmd="$1"
  local preview_cmd="$2"
  if ! {fn}_have fzf; then
    return 1
  fi
  eval "$source_cmd" | fzf --height=40% --layout=reverse --preview "$preview_cmd"
}}

{fn}_compadd_chroots() {{
  local -a names
  names=($({fn}_dynamic __complete chroots))
  compadd -a names
}}

{fn}_fzf_chroot() {{
  local selection
  selection=$({fn}_fzf_pick "{fn}_dynamic __complete chroot-details" "{fn}_dynamic __complete chroot-preview {{1}}")
  [[ -n "$selection" ]] || return 1
  compadd -- "${{selection%%$'\\t'*}}"
}}

{fn}_complete_chroot_arg() {{
  if {fn}_have fzf; then
    {fn}_fzf_chroot && return
  fi
  {fn}_compadd_chroots
}}

{fn}_complete_config_path() {{
  if {fn}_have fzf; then
    local picked
    picked=$({fn}_fzf_pick "print -rl -- **/*(.N)" "{fn}_preview_file {{1}}")
    [[ -n "$picked" ]] && compadd -- "$picked" && return
  fi
  _files
}}

{fn}_complete_after_dashdash() {{
  _normal
}}

{fn}() {{
  local curcontext="$curcontext" state line
  typeset -A opt_args

  _arguments -C \\
    '--config[Path to config file]:config:{fn}_complete_config_path' \\
    '--dry-run[Do not execute commands]' \\
    '--verbose[Enable verbose output]' \\
    '--no-sudo[Disable automatic sudo escalation]' \\
    '--name[Chroot name]:chroot name:{fn}_complete_chroot_arg' \\
    '1:command:({commands})' \\
    '*::args:->args'

  case $state in
    args)
      case $words[1] in
        completion)
          _arguments '1:shell:({completion_subcommands})'
          ;;
        status)
          _arguments '--verbose[Show path existence and extra details]'
          ;;
        mount|unmount|fix-tty|doctor)
          ;;
        logs)
          _arguments '--tail[Number of lines to show]:lines' '--all[Show full log]'
          ;;
        start|restart)
          if (( CURRENT > 2 )) && [[ " ${{words[*]}} " == *" -- "* ]]; then
            {fn}_complete_after_dashdash
            return
          fi
          _arguments \\
            '--login[Open login shell for configured user]' \\
            '--root-login[Open login shell as root]' \\
            '--exec-command[Execute command string]:command'
          ;;
        exec)
          if (( CURRENT > 2 )) && [[ " ${{words[*]}} " == *" -- "* ]]; then
            {fn}_complete_after_dashdash
            return
          fi
          _arguments \\
            '--root[Execute as root]' \\
            '--command[Execute command string]:command'
          ;;
        install)
          _arguments \\
            '1:distro:({distros})' \\
            '--phase[Installation phase]:phase:({phases})' \\
            '--force-phase[Bypass phase gating]' \\
            '--auto[Run through remaining phases automatically]' \\
            '--resume[Resume from next actionable phase]' \\
            '--repair[Re-run current phase in repair mode]' \\
            '--list-versions[List available versions]' \\
            '--version[Version label]:version' \\
            '--release[Release codename]:release' \\
            '--username[Username to create or sync]:username' \\
            '--desktop[Desktop selection]:desktop:({desktops})' \\
            '--profile[Install profile]:profile:({profiles})'
          ;;
        upgrade)
          _arguments '--username[Username for ownership sync and hooks]:username'
          ;;
        chroots)
          if (( CURRENT == 3 )); then
            compadd {chroots_subcommands}
            return
          fi
          case $words[3] in
            list)
              ;;
            show|remove)
              {fn}_complete_chroot_arg
              ;;
            rename)
              if (( CURRENT == 4 )); then
                {fn}_complete_chroot_arg
              else
                {fn}_complete_chroot_arg
              fi
              ;;
          esac
          ;;
        users)
          if (( CURRENT == 3 )); then
            compadd {users_subcommands}
            return
          fi
          case $words[3] in
            show-id)
              _arguments '--username[Username to inspect]:username'
              ;;
            sync-id)
              _arguments '--username[Username to sync]:username' '--no-fix-ownership[Skip recursive chown]'
              ;;
          esac
          ;;
      esac
      ;;
  esac
}}

compdef {fn} {prog}
"""


def completion_chroot_names(records: Iterable[dict[str, object]]) -> str:
    names = sorted(str(record["name"]) for record in records if "name" in record)
    return "\n".join(names)


def completion_chroot_details(records: Iterable[dict[str, object]]) -> str:
    lines: list[str] = []
    for record in sorted(records, key=lambda item: str(item.get("name", ""))):
        lines.append(
            "\t".join(
                [
                    str(record.get("name", "")),
                    str(record.get("distro", "")),
                    str(record.get("phase", "")),
                    str(record.get("version", "")),
                    str(record.get("release_name", "")),
                    "installed" if bool(record.get("installed")) else "pending",
                ]
            )
        )
    return "\n".join(lines)


def completion_chroot_preview(record: dict[str, object] | None) -> str:
    if record is None:
        return ""
    metadata = record.get("metadata", {})
    lines = [
        f"name: {record.get('name', '')}",
        f"distro: {record.get('distro', '')}",
        f"phase: {record.get('phase', '')}",
        f"installed: {record.get('installed', '')}",
        f"version: {record.get('version', '')}",
        f"release: {record.get('release_name', '')}",
        f"path: {record.get('path', '')}",
    ]
    if isinstance(metadata, dict):
        for key, value in sorted(metadata.items()):
            lines.append(f"metadata.{key}: {value}")
    return "\n".join(lines)
