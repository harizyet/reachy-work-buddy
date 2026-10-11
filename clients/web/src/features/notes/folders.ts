import type { Note } from '../../api/types';

/** A note's tag is its folder under All Notes: slash-separated names, e.g. "Projects/Project StarWars/Finance". Same rules as shared/models/note_tag.py. */
export const ROOT = 'All Notes';
export const MAX_DEPTH = 5;
export const MAX_SEGMENT_LENGTH = 60;

export class TagError extends Error {}

/** The canonical tag for what was typed, or null for none (blank, or just "All Notes"). Throws TagError when it is too deep or a name is too long. */
export function normaliseTag(raw: string): string | null {
  let parts = raw.split('/').map((p) => p.split(/\s+/).filter(Boolean).join(' ')).filter(Boolean);
  if (parts[0]?.toLowerCase() === ROOT.toLowerCase()) parts = parts.slice(1);
  if (parts.length === 0) return null;
  if (parts.length > MAX_DEPTH) throw new TagError(`A folder can have at most ${MAX_DEPTH} levels.`);
  if (parts.some((p) => p.length > MAX_SEGMENT_LENGTH)) throw new TagError(`Each folder name can have at most ${MAX_SEGMENT_LENGTH} characters.`);
  return parts.join('/');
}

export interface FolderNode {
  path: string; // the tag that selects this folder
  name: string; // last level
  depth: number; // 0 for a folder directly under All Notes
  count: number; // notes in this folder and below it
  children: FolderNode[];
}

/** The folder tree implied by the notes' tags. A folder exists while a note is filed in it or below it. */
export function buildTree(notes: Note[]): FolderNode[] {
  const roots: FolderNode[] = [];
  for (const note of notes) {
    if (!note.tag) continue;
    let level = roots;
    let path = '';
    note.tag.split('/').forEach((name, depth) => {
      path = path ? `${path}/${name}` : name;
      let node = level.find((n) => n.name.toLowerCase() === name.toLowerCase());
      if (!node) {
        node = { path, name, depth, count: 0, children: [] };
        level.push(node);
      }
      node.count += 1;
      level = node.children;
    });
  }
  const sort = (nodes: FolderNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

export function flatten(nodes: FolderNode[]): FolderNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)]);
}

/** null is All Notes (everything); a folder holds its own notes and those of the folders below it. */
export function inFolder(note: Note, folder: string | null): boolean {
  if (folder === null) return true;
  const tag = (note.tag ?? '').toLowerCase();
  const want = folder.toLowerCase();
  return tag === want || tag.startsWith(`${want}/`);
}
