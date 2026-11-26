const paths = {
  search: '<circle cx="10.7" cy="10.7" r="6.2"/><path d="m15.4 15.4 4.1 4.1"/>',
  expand: '<path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5"/>',
  record: '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
  play: '<path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M7 5h3v14H7zm7 0h3v14h-3z" fill="currentColor" stroke="none"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v6m0-10v.5"/>',
  route: '<path d="M5 18c0-7 14-5 14-12M3 18h4m10-12h4"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  warning: '<path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3v.5"/>',
  airport: '<path d="M12 3v18M3 11l9-3 9 3M7 19l5-2 5 2"/>',
};

export function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? paths.info}</svg>`;
}

export const planeIcon = '<svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M14.4 3.6c.2-1 1-1.6 1.6-1.6s1.4.6 1.6 1.6l1.1 9.4 10.1 6.2v2.5l-10.1-3.2-.5 7 3.4 2.5v1.8l-5.6-1.6-5.6 1.6V28l3.4-2.5-.5-7-10.1 3.2v-2.5L13.3 13Z"/></svg>';
export const unknownTrackIcon = '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="16" cy="16" r="6"/><circle cx="16" cy="16" r="1.5" fill="currentColor"/></svg>';
