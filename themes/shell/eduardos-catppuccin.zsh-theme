# eduardOS — Catppuccin Mocha prompt for Oh My Zsh.
# Adapted only from the public Catppuccin palette, no network lookups.
# Minimal per-prompt work: use Oh My Zsh's git helper.
ZSH_THEME_GIT_PROMPT_PREFIX='%F{#a6e3a1} '
ZSH_THEME_GIT_PROMPT_SUFFIX='%f'
ZSH_THEME_GIT_PROMPT_DIRTY='%F{#f9e2af} ●%f'
ZSH_THEME_GIT_PROMPT_CLEAN=''
setopt PROMPT_SUBST
PROMPT='%F{#fab387}╭─%f %F{#89b4fa}%n%f%F{#6c7086}@%f%F{#94e2d5}%m%f %F{#cba6f7}%~%f $(git_prompt_info)
%F{#fab387}╰─❯%f '
