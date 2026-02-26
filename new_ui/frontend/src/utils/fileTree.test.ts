import { describe, it, expect } from 'vitest';
import { buildTree } from './fileTree';

describe('buildTree', () => {
  it('builds a hierarchical tree from flat paths', () => {
    const tree = buildTree([
      'src/main.ts',
      'src/components/Button.tsx',
      'README.md',
    ]);

    expect(tree).toEqual([
      {
        name: 'src',
        type: 'folder',
        children: [
          {
            name: 'components',
            type: 'folder',
            children: [{ name: 'Button.tsx', type: 'file', children: undefined }],
          },
          { name: 'main.ts', type: 'file', children: undefined },
        ],
      },
      { name: 'README.md', type: 'file', children: undefined },
    ]);
  });

  it('deduplicates duplicate file paths', () => {
    const tree = buildTree([
      'a/b/c.txt',
      'a/b/c.txt',
      'a/b/d.txt',
    ]);

    expect(tree).toEqual([
      {
        name: 'a',
        type: 'folder',
        children: [
          {
            name: 'b',
            type: 'folder',
            children: [
              { name: 'c.txt', type: 'file', children: undefined },
              { name: 'd.txt', type: 'file', children: undefined },
            ],
          },
        ],
      },
    ]);
  });

  it('ignores empty paths and empty path segments', () => {
    const tree = buildTree([
      '',
      '   ',
      '/',
      'docs//guide.md',
    ]);

    expect(tree).toEqual([
      {
        name: 'docs',
        type: 'folder',
        children: [{ name: 'guide.md', type: 'file', children: undefined }],
      },
    ]);
  });
});
