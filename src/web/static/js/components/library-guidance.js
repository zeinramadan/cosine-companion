/* User-facing recovery copy shared by destinations that need an index. */

export const FIRST_RUN_GUIDANCE =
  'Export your collection from Rekordbox with File → Export Collection in XML format. ' +
  'Then open Settings, save the XML path, and choose Index New Tracks.';

export function firstRunGuidance(context) {
  return `${context} ${FIRST_RUN_GUIDANCE}`;
}
