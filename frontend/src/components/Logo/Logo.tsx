/**
 * The DeepMatter mark: a brain drawn as one continuous weight of line.
 *
 * Monoline and geometric rather than anatomical, so it survives being 20px in a
 * header and stays legible as a favicon. Two mirrored lobes with a seam down the
 * middle read as a brain immediately; the folds inside each lobe are curves off
 * that seam, which is what keeps it from reading as a walnut.
 *
 * Drawn in `currentColor` with no fills, so it takes the colour of whatever it
 * sits in — white on the gradient tile in the header, ink on a plain background —
 * and needs no second asset for dark mode.
 */
export function Logo({ className = '', title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
    >
      {title ? <title>{title}</title> : null}
      {/* The brain is in the silhouette, not in interior detail.
          Five scallops down each side read as gyri at any size, where interior
          folds turn to mush below about 24px — which is where a header mark and
          a favicon both live. */}
      {/* Scalloped lobes. The bumps are the gyri, and they are in the outline
          rather than inside it because a silhouette survives being small. No
          taper toward the base: narrowing it turns the whole mark into a map
          pin, which is the last thing an app that finds local events should
          look like. */}
      <path d="M12 3.9C10.6 3.1 8.7 3.4 7.9 4.8C6.2 4.7 4.8 6.1 5.1 7.8C3.6 8.6 3.3 10.7 4.6 11.9C3.6 13.2 4.1 15.2 5.6 16C5.7 17.8 7.4 19.1 9.2 18.8C10 19.9 11 20.3 12 20.1" />
      <path d="M12 3.9C13.4 3.1 15.3 3.4 16.1 4.8C17.8 4.7 19.2 6.1 18.9 7.8C20.4 8.6 20.7 10.7 19.4 11.9C20.4 13.2 19.9 15.2 18.4 16C18.3 17.8 16.6 19.1 14.8 18.8C14 19.9 13 20.3 12 20.1" />
      {/* One fold per lobe, concentric with the outline. This is what keeps the
          mark from collapsing to a bisected circle at 20px, where the scallops
          are too fine to read. */}
      <path d="M12 7.6C10.1 7.6 8.6 9.1 8.6 11.0C8.6 12.4 9.4 13.6 10.6 14.2" />
      <path d="M12 7.6C13.9 7.6 15.4 9.1 15.4 11.0C15.4 12.4 14.6 13.6 13.4 14.2" />
      {/* The seam, which is what turns two lobes into one brain. */}
      <path d="M12 3.9V20.1" />
    </svg>
  )
}
