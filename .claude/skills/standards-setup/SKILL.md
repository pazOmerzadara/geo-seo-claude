# Standards Integration Skill
1. Add claude-standards as git submodule: git submodule add <repo-url> .claude/standards
2. Create symlinks from .claude/ to .claude/standards/ for shared files
3. Verify all symlink targets exist in the upstream repo before creating
4. Do NOT duplicate any content that exists in claude-standards
5. Keep only repo-specific content in local CLAUDE.md
6. Create PR targeting both dev and main
