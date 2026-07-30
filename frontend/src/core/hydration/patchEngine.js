function shallowEqual(a, b) {
  if (a === b) return true;
  if (!a || !b) return false;
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (a[key] !== b[key]) return false;
  }
  return true;
}

export function patchRows(prevRows, nextRows, options = {}) {
  const {
    keyFn = (row) => row?.id ?? row?.key ?? row?.symbol ?? row?.strike,
    mergeFn = (prev, next) => ({ ...prev, ...next }),
    equalFn = shallowEqual,
  } = options;

  if (!Array.isArray(nextRows) || nextRows.length === 0) {
    return prevRows || [];
  }

  const prevList = Array.isArray(prevRows) ? prevRows : [];
  const prevByKey = new Map();
  for (const row of prevList) {
    const key = keyFn(row);
    if (key != null) prevByKey.set(String(key), row);
  }

  let changed = false;
  const patched = nextRows.map((nextRow) => {
    const key = keyFn(nextRow);
    if (key == null) {
      changed = true;
      return nextRow;
    }
    const prevRow = prevByKey.get(String(key));
    if (!prevRow) {
      changed = true;
      return nextRow;
    }
    const merged = mergeFn(prevRow, nextRow);
    if (equalFn(prevRow, merged)) return prevRow;
    changed = true;
    return merged;
  });

  if (!changed && prevList.length === patched.length) return prevList;
  return patched;
}

export function patchObject(prevObj, nextObj, equalFn = shallowEqual) {
  if (!prevObj) return nextObj || {};
  if (!nextObj) return prevObj;
  const merged = { ...prevObj, ...nextObj };
  return equalFn(prevObj, merged) ? prevObj : merged;
}
