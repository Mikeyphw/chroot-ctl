#compdef chrootctl chc

typeset -g _chrootctl_prog="chrootctl"

_chrootctl_have() {
  (( $+commands[$1] ))
}

_chrootctl_dynamic() {
  "${_chrootctl_prog}" "$@" 2>/dev/null
}

_chrootctl_preview_file() {
  local target="$1"
  if [[ -d "$target" ]]; then
    if _chrootctl_have lsd; then
      lsd --color=always "$target" 2>/dev/null
    else
      ls -lah "$target" 2>/dev/null
    fi
    return
  fi
  if _chrootctl_have bat; then
    bat --style=plain --color=always --line-range=:120 "$target" 2>/dev/null
  else
    sed -n '1,120p' "$target" 2>/dev/null
  fi
}

_chrootctl_fzf_pick() {
  local source_cmd="$1"
  local preview_cmd="$2"
  if ! _chrootctl_have fzf; then
    return 1
  fi
  eval "$source_cmd" | fzf --height=40% --layout=reverse --preview "$preview_cmd"
}

_chrootctl_compadd_chroots() {
  local -a names
  names=($(_chrootctl_dynamic __complete chroots))
  compadd -a names
}

_chrootctl_compadd_installed_chroots() {
  local -a names
  names=($(_chrootctl_dynamic __complete installed-chroots))
  compadd -a names
}

_chrootctl_fzf_chroot() {
  local selection
  selection=$(_chrootctl_fzf_pick "_chrootctl_dynamic __complete chroot-details" "_chrootctl_dynamic __complete chroot-preview {1}")
  [[ -n "$selection" ]] || return 1
  compadd -- "${selection%%$'	'*}"
}

_chrootctl_fzf_installed_chroot() {
  local selection
  selection=$(_chrootctl_fzf_pick "_chrootctl_dynamic __complete installed-chroots" "_chrootctl_dynamic __complete chroot-preview {1}")
  [[ -n "$selection" ]] || return 1
  compadd -- "${selection%%$'	'*}"
}

_chrootctl_complete_chroot_arg() {
  if _chrootctl_have fzf; then
    _chrootctl_fzf_chroot && return
  fi
  _chrootctl_compadd_chroots
}

_chrootctl_complete_installed_chroot_arg() {
  if _chrootctl_have fzf; then
    _chrootctl_fzf_installed_chroot && return
  fi
  _chrootctl_compadd_installed_chroots
}

_chrootctl_complete_config_path() {
  if _chrootctl_have fzf; then
    local picked
    picked=$(_chrootctl_fzf_pick "print -rl -- **/*(.N)" "_chrootctl_preview_file {1}")
    [[ -n "$picked" ]] && compadd -- "$picked" && return
  fi
  _files
}

_chrootctl_compadd_users() {
  local -a names
  names=($(_chrootctl_dynamic __complete users))
  compadd -a names
}

_chrootctl_compadd_tools() {
  local -a names
  names=($(_chrootctl_dynamic __complete tools))
  compadd -a names
}

_chrootctl_compadd_addons() {
  local -a names
  names=($(_chrootctl_dynamic __complete addons))
  compadd -a names
}

_chrootctl_compadd_tool_categories() {
  local distro="${opt_args[--distro]}"
  local -a categories
  categories=($(_chrootctl_dynamic __complete tool-categories "$distro"))
  compadd -a categories
}

_chrootctl_compadd_addon_categories() {
  local distro="${opt_args[--distro]}"
  local -a categories
  categories=($(_chrootctl_dynamic __complete addon-categories "$distro"))
  compadd -a categories
}

_chrootctl_fzf_catalog_pick() {
  local topic_prefix="$1"
  local selection
  selection=$(_chrootctl_fzf_pick "_chrootctl_dynamic __complete ${topic_prefix}-details" "_chrootctl_dynamic __complete ${topic_prefix}-preview {1}")
  [[ -n "$selection" ]] || return 1
  compadd -- "${selection%%$'	'*}"
}

_chrootctl_complete_tool_arg() {
  if _chrootctl_have fzf; then
    _chrootctl_fzf_catalog_pick tool && return
  fi
  _chrootctl_compadd_tools
}

_chrootctl_complete_addon_arg() {
  if _chrootctl_have fzf; then
    _chrootctl_fzf_catalog_pick addon && return
  fi
  _chrootctl_compadd_addons
}

_chrootctl_complete_after_dashdash() {
  _normal
}

_chrootctl() {
  local curcontext="$curcontext" state line
  typeset -A opt_args
  _chrootctl_prog="${words[1]:-chrootctl}"

  _arguments -C     '--config[Path to config file]:config:_chrootctl_complete_config_path'     '--dry-run[Do not execute commands]'     '--verbose[Enable verbose output]'     '--json[Emit machine-readable JSON for supported commands]'     '--no-sudo[Disable automatic sudo escalation]'     '--name[Target chroot name]:chroot name:_chrootctl_complete_chroot_arg'     '--non-interactive[Fail instead of prompting]'     '1:command:(status mount unmount fix-tty doctor logs start restart exec install upgrade completion wrapper chroots users tools addons)'     '*::args:->args'

  case $state in
    args)
      case $words[1] in
        completion)
          _arguments '1:shell:(zsh)'
          ;;
        wrapper)
          if (( CURRENT == 3 )); then
            compadd install
            return
          fi
          case $words[3] in
            install)
              _arguments                 '--dir[Wrapper install directory]:directory:_files -/'                 '--name[Wrapper command name]:name'                 '--completion-dir[zsh site-functions directory]:directory:_files -/'                 '--no-completion[Do not install zsh completion]'
              ;;
          esac
          ;;
        status)
          _arguments '--details[Show path existence and extra details]'
          ;;
        mount|unmount|fix-tty|doctor)
          ;;
        logs)
          _arguments             '--tail[Number of lines to show]:lines'             '--all[Show full log]'             '--follow[Keep streaming appended log lines]'             '--level[Minimum severity to include]:level:(DEBUG INFO WARNING ERROR CRITICAL)'
          ;;
        start|restart)
          if (( CURRENT > 2 )) && [[ " ${words[*]} " == *" -- "* ]]; then
            _chrootctl_complete_after_dashdash
            return
          fi
          _arguments             '--login[Open login shell for configured user]'             '--root-login[Open login shell as root]'             '--x11[Prepare Termux:X11 on host and export DISPLAY/PULSE_SERVER]'
          ;;
        exec)
          if (( CURRENT > 2 )) && [[ " ${words[*]} " == *" -- "* ]]; then
            _chrootctl_complete_after_dashdash
            return
          fi
          _arguments             '--root[Execute as root]'             '--command[Execute command string]:command'             '--x11[Prepare Termux:X11 on host and export DISPLAY/PULSE_SERVER]'
          ;;
        install)
          _arguments             '1:distro:(ubuntu arch)'             '--phase[Installation phase]:phase:(extract bootstrap desktop finalize)'             '--force-phase[Bypass phase gating]'             '--resume[Resume from next actionable phase]'             '--repair[Re-run current phase in repair mode]'             '--list-versions[List available versions]'             '--version[Version label]:version'             '--release[Release codename]:release'             '--username[Username to create or sync]:username'             '--desktop[Desktop selection]:desktop:(xfce4 plasma none)'             '--profile[Install profile]:profile:(minimal dev xfce4 plasma custom)'             '--tool[Tool to apply after finalize]:tool:_chrootctl_complete_tool_arg'             '--addon[Addon to apply after finalize]:addon:_chrootctl_complete_addon_arg'             '--select-tools[Select tools with fzf if available]'             '--select-addons[Select addons with fzf if available]'
          ;;
        upgrade)
          _arguments '--username[Username for ownership sync and hooks]:username'
          ;;
        chroots)
          if (( CURRENT == 3 )); then
            compadd list show remove rename
            return
          fi
          case $words[3] in
            rename)
              _arguments '1:new-name:'
              ;;
          esac
          ;;
        users)
          if (( CURRENT == 3 )); then
            compadd list show add remove password shell sudo show-id sync-id
            return
          fi
          case $words[3] in
            list)
              ;;
            show|remove|password)
              _arguments '1:user:_chrootctl_compadd_users'
              ;;
            add)
              _arguments '--shell[Login shell]:shell:_files' '--sudo[Grant sudo access]' '1:username:'
              ;;
            shell)
              _arguments '--shell[Login shell]:shell:_files' '1:user:_chrootctl_compadd_users'
              ;;
            sudo)
              _arguments '--enable[Enable sudo]' '--disable[Disable sudo]' '1:user:_chrootctl_compadd_users'
              ;;
            show-id)
              _arguments '1:user:_chrootctl_compadd_users'
              ;;
            sync-id)
              _arguments '--no-fix-ownership[Skip recursive chown]' '1:user:_chrootctl_compadd_users'
              ;;
          esac
          ;;
        tools)
          if (( CURRENT == 3 )); then
            compadd categories list show apply
            return
          fi
          case $words[3] in
            categories)
              _arguments '--distro[Filter by distro]:distro:(ubuntu arch)'
              ;;
            list)
              _arguments '--distro[Filter by distro]:distro:(ubuntu arch)' '--category[Filter by category]:category:_chrootctl_compadd_tool_categories'
              ;;
            apply)
              _arguments '--category[Filter interactive selection by category]:category:_chrootctl_compadd_tool_categories' '1:tool:_chrootctl_complete_tool_arg' '*:tool:_chrootctl_compadd_tools'
              ;;
            show)
              _arguments '1:tool:_chrootctl_complete_tool_arg'
              ;;
          esac
          ;;
        addons)
          if (( CURRENT == 3 )); then
            compadd categories list show apply
            return
          fi
          case $words[3] in
            categories)
              _arguments '--distro[Filter by distro]:distro:(ubuntu arch)'
              ;;
            list)
              _arguments '--distro[Filter by distro]:distro:(ubuntu arch)' '--category[Filter by category]:category:_chrootctl_compadd_addon_categories'
              ;;
            apply)
              _arguments '--category[Filter interactive selection by category]:category:_chrootctl_compadd_addon_categories' '1:addon:_chrootctl_complete_addon_arg' '*:addon:_chrootctl_compadd_addons'
              ;;
            show)
              _arguments '1:addon:_chrootctl_complete_addon_arg'
              ;;
          esac
          ;;
      esac
      ;;
  esac
}

compdef _chrootctl chrootctl chc
