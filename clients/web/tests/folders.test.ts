import { describe, expect, it } from 'vitest';
import { buildTree, flatten, inFolder, normaliseTag, TagError } from '../src/features/notes/folders';
import type { Note } from '../src/api/types';

const note = (tag: string | null): Note => ({ id: tag ?? 'none', title: 't', body: '', updated_at: new Date().toISOString(), tag });

describe('normaliseTag (same cases as services/companion-core/tests/test_note_tag.py)', () => {
  it.each([
    ['', null],
    ['  /  ', null],
    ['All Notes', null],
    ['Meeting Notes', 'Meeting Notes'],
    ['All Notes/Meeting Notes', 'Meeting Notes'],
    ['all notes/Projects/Project StarWars/Finance', 'Projects/Project StarWars/Finance'],
    [' Projects // Project   StarWars /Finance/ ', 'Projects/Project StarWars/Finance'],
    ['Projects/All Notes', 'Projects/All Notes'],
    ['a\nb/c\td', 'a b/c d'],
  ])('%j -> %j', (raw, expected) => expect(normaliseTag(raw)).toBe(expected));

  it('bounds depth and name length', () => {
    expect(normaliseTag('a/b/c/d/e')).toBe('a/b/c/d/e');
    expect(() => normaliseTag('a/b/c/d/e/f')).toThrow(TagError);
    expect(normaliseTag('x'.repeat(60))).toBe('x'.repeat(60));
    expect(() => normaliseTag('x'.repeat(61))).toThrow(TagError);
  });
});

describe('folder tree', () => {
  it('counts a folder with the notes below it, merges names that differ only in case and sorts', () => {
    const tree = buildTree([note('Projects/Finance'), note('projects'), note('Projects/Finance'), note('Alpha'), note(null)]);
    expect(tree.map((n) => [n.name, n.count])).toEqual([['Alpha', 1], ['Projects', 3]]);
    expect(flatten(tree).map((n) => [n.path, n.depth])).toEqual([['Alpha', 0], ['Projects', 0], ['Projects/Finance', 1]]);
  });

  it('matches a folder by whole path levels only', () => {
    expect(inFolder(note('Projects/Finance'), 'Projects')).toBe(true);
    expect(inFolder(note('Projects'), 'Projects')).toBe(true);
    expect(inFolder(note('Projects2'), 'Projects')).toBe(false);
    expect(inFolder(note(null), 'Projects')).toBe(false);
    expect(inFolder(note(null), null)).toBe(true);
  });
});
