# replace <PATH_TO_BACKUP> with the backup path printed above
cp "<PATH_TO_BACKUP>" "$HOME/.continue/$(basename "<PATH_TO_BACKUP>" | sed 's/\.bak\..*$//')"