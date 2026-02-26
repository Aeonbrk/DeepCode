export interface FileNode {
  name: string;
  type: 'file' | 'folder';
  children?: FileNode[];
}

interface FileNodeMap {
  [name: string]: {
    name: string;
    type: 'file' | 'folder';
    children?: FileNodeMap;
  };
}

export function buildTree(paths: string[]): FileNode[] {
  const root: FileNodeMap = {};

  for (const rawPath of paths) {
    const parts = rawPath
      .trim()
      .split('/')
      .map((part) => part.trim())
      .filter(Boolean);

    if (parts.length === 0) {
      continue;
    }

    let current = root;

    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      const isFile = index === parts.length - 1;
      const existing = current[part];

      if (!existing) {
        current[part] = {
          name: part,
          type: isFile ? 'file' : 'folder',
          children: isFile ? undefined : {},
        };
      } else if (!isFile && existing.type === 'file') {
        existing.type = 'folder';
        existing.children = existing.children ?? {};
      }

      if (!isFile) {
        const nextNode = current[part];
        nextNode.children = nextNode.children ?? {};
        current = nextNode.children;
      }
    }
  }

  const toArray = (nodeMap: FileNodeMap): FileNode[] => {
    return Object.values(nodeMap)
      .map((node) => ({
        name: node.name,
        type: node.type,
        children: node.children ? toArray(node.children) : undefined,
      }))
      .sort((left, right) => {
        if (left.type !== right.type) {
          return left.type === 'folder' ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });
  };

  return toArray(root);
}
