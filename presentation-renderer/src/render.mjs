import pptxgen from 'pptxgenjs'

const MIME_PREFIX = {
  'image/png': 'image/png',
  'image/jpeg': 'image/jpeg',
  'image/webp': 'image/webp',
}

// Resolve a validated image reference into an in-memory data URI.
const imageData = (artifactId, images) => {
  const image = images?.[artifactId]
  if (!image || !MIME_PREFIX[image.mime_type] || !image.base64) {
    throw new Error(`Missing presentation image ${artifactId}`)
  }
  return `data:${MIME_PREFIX[image.mime_type]};base64,${image.base64}`
}

// Add one validated editable element to a PptxGenJS slide.
const addElement = (pptx, slide, element, theme, images) => {
  const position = { x: element.x, y: element.y, w: element.w, h: element.h }
  if (element.type === 'text') {
    slide.addText(element.text, {
      ...position,
      fontFace: theme.font_face,
      fontSize: element.font_size,
      bold: element.bold,
      color: element.color || theme.text_color,
      align: element.align,
      valign: element.valign,
      bullet: element.bullet ? { type: 'bullet' } : undefined,
      breakLine: false,
      margin: 0.08,
      fit: 'shrink',
    })
    return
  }
  if (element.type === 'shape') {
    slide.addShape(pptx.ShapeType[element.shape], {
      ...position,
      fill: { color: element.fill_color },
      line: { color: element.line_color, width: element.line_width },
    })
    return
  }
  if (element.type === 'chart') {
    const chartType = {
      bar: pptx.ChartType.bar,
      column: pptx.ChartType.bar,
      line: pptx.ChartType.line,
      pie: pptx.ChartType.pie,
    }[element.chart_type]
    const data = element.series.map(series => ({
      name: series.name,
      labels: element.categories,
      values: series.values,
    }))
    slide.addChart(chartType, data, {
      ...position,
      barDir: element.chart_type === 'bar' ? 'bar' : 'col',
      catAxisLabelFontFace: theme.font_face,
      valAxisLabelFontFace: theme.font_face,
      chartColors: [theme.primary_color, '5856D6', '34C759', 'FF9500'],
      showLegend: element.show_legend,
      showTitle: element.show_title,
      title: element.title || '',
      showValue: false,
      showCategoryName: false,
    })
    return
  }
  if (element.type === 'table') {
    const rows = [element.headers, ...element.rows]
    slide.addTable(rows, {
      ...position,
      fontFace: theme.font_face,
      fontSize: element.font_size,
      color: theme.text_color,
      border: { type: 'solid', color: 'D2D2D7', pt: 1 },
      fill: 'FFFFFF',
      margin: 0.08,
      autoFit: false,
      bold: false,
      rowH: element.h / rows.length,
    })
    return
  }
  if (element.type === 'image') {
    slide.addImage({
      ...position,
      // Preserve the picture's aspect ratio within its box instead of stretching
      // it, so an image is never distorted if it is not a perfect fit.
      sizing: { type: 'contain', w: position.w, h: position.h },
      data: imageData(element.artifact_id, images),
      altText: element.alt_text,
    })
    return
  }
  throw new Error(`Unsupported presentation element type: ${element.type}`)
}

// Compile one validated DeckSpec into a native editable OOXML presentation.
export const renderPresentation = async (specification, images = {}) => {
  const pptx = new pptxgen()
  pptx.layout = 'LAYOUT_WIDE'
  pptx.author = 'AniOS'
  pptx.company = 'AniOS'
  pptx.subject = specification.subtitle || specification.title
  pptx.title = specification.title
  pptx.lang = 'en-US'
  pptx.theme = {
    headFontFace: specification.theme.font_face,
    bodyFontFace: specification.theme.font_face,
    lang: 'en-US',
  }

  for (const slideSpec of specification.slides) {
    const slide = pptx.addSlide()
    slide.background = {
      color: slideSpec.background_color || specification.theme.background_color,
    }
    for (const element of slideSpec.elements) {
      addElement(pptx, slide, element, specification.theme, images)
    }
    if (slideSpec.notes) slide.addNotes(slideSpec.notes)
  }

  return Buffer.from(await pptx.write({ outputType: 'nodebuffer' }))
}
