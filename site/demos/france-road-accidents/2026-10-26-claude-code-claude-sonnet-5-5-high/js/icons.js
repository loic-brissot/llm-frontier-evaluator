// Hand-drawn 24×24 line icons (stroke only, inherit currentColor).
const P = {
  ped: '<circle cx="12" cy="4.6" r="1.9"/><path d="M12 8.2v6.2M12 14.4l-3 6.4M12 14.4l3 6.4M12 10.3l-4 2.5M12 10.3l4 2.2"/>',
  bike: '<circle cx="6" cy="16.5" r="3.6"/><circle cx="18" cy="16.5" r="3.6"/><path d="M6 16.5l3.5-7h5.5l3 7M9.5 9.5l2.7 7M15 9.5l-2.8 7M13.8 7.3h2.4M8.4 7.6h2.4"/>',
  edp: '<circle cx="6" cy="18.4" r="1.9"/><circle cx="18" cy="18.4" r="1.9"/><path d="M8 18.4h8M18 16.5L16.2 5.2M14.3 5.2h4.2"/>',
  moto: '<circle cx="5.5" cy="16.5" r="3.2"/><circle cx="18.5" cy="16.5" r="3.2"/><path d="M5.5 16.5l3.4-5.6h5.2l4.4 5.6M14.1 10.9l-1-3.6h3M8.9 10.9H6.6M10 16.5h4"/>',
  car: '<path d="M3.2 15.8v-3l2.2-3.6c.3-.5.8-.8 1.4-.8h8.2c.5 0 1 .2 1.3.6l3 3.8h1.5v3"/><path d="M3.2 15.8h2.1M8.7 15.8h6.6M18.7 15.8h2.1M5.6 11.6h12.6"/><circle cx="7" cy="16.4" r="1.8"/><circle cx="17" cy="16.4" r="1.8"/>',
  van: '<path d="M2.6 16.6V7.8c0-.6.4-1 1-1H14c.6 0 1 .4 1 1v2.4h3.2l3 3.6v2.8h-1.4M2.6 16.6h2.6M8.8 16.6h6.4"/><path d="M15 10.2v4"/><circle cx="7" cy="17" r="1.8"/><circle cx="17.2" cy="17" r="1.8"/>',
  hgv: '<path d="M1.8 17V7.2c0-.6.4-1 1-1h10.8c.6 0 1 .4 1 1V17M14.6 9.6h4l3.4 3.6V17h-1.2M1.8 17h2.6M9.4 17h5.2"/><circle cx="6.8" cy="17.4" r="1.9"/><circle cx="17.8" cy="17.4" r="1.9"/>',
  oth: '<circle cx="7.4" cy="16" r="4"/><circle cx="18" cy="17.2" r="2.4"/><path d="M7.4 12V7.4h6.2l2 4.4h3.4v5.4M4 8h3.4"/>',
  animal: '<circle cx="6.6" cy="10.4" r="1.7"/><circle cx="10.6" cy="6.6" r="1.7"/><circle cx="15.2" cy="6.6" r="1.7"/><circle cx="19" cy="10.4" r="1.7"/><path d="M12.9 11.8c-3 0-5.4 3-5.4 5.2 0 2.2 2.3 2.2 5.4 1.2 3.100 1 5.4 1 5.400-1.200 0-2.200-2.400-5.200-5.400-5.200z"/>',
  obstacle: '<path d="M12 21v-6.5"/><path d="M12 14.6c-4 0-6.300-3-5.300-6 .6-2.800 3-4.600 5.300-4.600s4.700 1.800 5.300 4.600c1 3-1.300 6-5.300 6z"/>',
  none: '<circle cx="12" cy="12" r="7.4"/><path d="M6.800 17.200L17.200 6.800"/>',
  filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  table: '<rect x="4" y="5" width="16" height="14" rx="1.5"/><path d="M4 10h16M4 14.500h16M10 5v14"/>',
  grid: '<circle cx="7" cy="7" r="2"/><circle cx="16.500" cy="7.500" r="3"/><circle cx="7.500" cy="16.500" r="3"/><circle cx="17" cy="17" r="1.500"/>',
  search: '<circle cx="10.500" cy="10.500" r="5.500"/><path d="M15 15l5 5"/>',
  reset: '<path d="M5 12a7 7 0 1 0 2.200-5.100M5 5v4.500h4.500"/>',
  info: '<circle cx="12" cy="12" r="8.500"/><path d="M12 11v5.500M12 7.600v.1"/>',
  chevL: '<path d="M14.500 6l-6 6 6 6"/>', chevR: '<path d="M9.500 6l6 6-6 6"/>', chevD: '<path d="M6 9.500l6 6 6-6"/>',
  pin: '<path d="M12 21s6.500-5.800 6.500-11A6.500 6.500 0 0 0 5.500 10c0 5.200 6.500 11 6.500 11z"/><circle cx="12" cy="10" r="2.300"/>',
  zoomIn: '<path d="M12 5v14M5 12h14"/>', zoomOut: '<path d="M5 12h14"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.700 0l3-3a4 4 0 0 0-5.700-5.700l-1 1M14 10a4 4 0 0 0-5.700 0l-3 3a4 4 0 0 0 5.700 5.700l1-1"/>',
  spark: '<path d="M12 3l1.800 5.200L19 10l-5.200 1.800L12 17l-1.800-5.200L5 10l5.200-1.800z"/>',
  user: '<circle cx="12" cy="8" r="3.200"/><path d="M5.500 19.500c.8-3.700 3.200-5.500 6.500-5.500s5.700 1.800 6.500 5.500"/>',
  helmet: '<path d="M4.500 15.500a7.500 7.500 0 0 1 15 0v2h-15z"/><path d="M4.500 13h8.500l2 2.500"/>',
  belt: '<path d="M7 4l10 16M7 4h3M17 20h-3"/>',
  clock: '<circle cx="12" cy="12" r="8.500"/><path d="M12 7v5l3.200 2"/>',
  road: '<path d="M8 3L5 21M16 3l3 18M12 4v3M12 10.500v3M12 17v3"/>',
};
export function icon(name, size = 16, cls = '') {
  return `<svg class="ico ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
}
export const MODE_ICON = ['ped', 'bike', 'edp', 'moto', 'car', 'van', 'hgv', 'oth'];
export const OPP_ICON = [...MODE_ICON, 'animal', 'obstacle', 'none'];
export const iconBody = (name) => P[name] || '';
