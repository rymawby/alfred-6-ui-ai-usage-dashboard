#!/usr/bin/osascript -l JavaScript
// Prints the CGWindowID of the Alfred UI window (so a capture never includes anything else).
ObjC.import('CoreGraphics');
function run() {
  const l = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, 0)));
  const w = l.filter(x => x.kCGWindowOwnerName === 'Alfred UI' && x.kCGWindowLayer === 0 && x.kCGWindowBounds.Width > 100);
  return w.map(x => x.kCGWindowNumber).join(' ');
}
