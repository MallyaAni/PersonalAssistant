import assert from 'node:assert/strict'
import test from 'node:test'
import { renderPresentation } from '../src/render.mjs'

// Prove the compiler emits a readable OOXML package from native object types.
test('renders a native editable presentation package', async () => {
  const content = await renderPresentation({
    schema_version: 1,
    title: 'Renderer acceptance',
    subtitle: 'Native editable objects',
    theme: {
      font_face: 'Aptos',
      background_color: 'F5F5F7',
      primary_color: '0071E3',
      text_color: '1D1D1F',
      muted_color: '6E6E73',
    },
    slides: [{
      slide_id: 'acceptance-slide',
      title: 'Editable objects',
      purpose: 'Prove native output',
      background_color: null,
      notes: 'Acceptance notes',
      elements: [
        {
          element_id: 'title',
          type: 'text',
          text: 'Editable title',
          x: 0.7,
          y: 0.5,
          w: 5,
          h: 0.7,
          font_size: 28,
          bold: true,
          color: null,
          align: 'left',
          valign: 'top',
          bullet: false,
        },
        {
          element_id: 'shape',
          type: 'shape',
          shape: 'roundRect',
          x: 0.7,
          y: 1.5,
          w: 2.2,
          h: 1,
          fill_color: 'FFFFFF',
          line_color: 'D2D2D7',
          line_width: 1,
        },
        {
          element_id: 'chart',
          type: 'chart',
          chart_type: 'column',
          x: 3.2,
          y: 1.4,
          w: 4.2,
          h: 2.6,
          categories: ['Q1', 'Q2'],
          series: [{ name: 'Revenue', values: [10, 14] }],
          show_legend: true,
          show_title: true,
          title: 'Revenue',
        },
        {
          element_id: 'table',
          type: 'table',
          x: 0.7,
          y: 4.3,
          w: 6.7,
          h: 1.5,
          headers: ['Metric', 'Value'],
          rows: [['Growth', '40%']],
          font_size: 16,
        },
      ],
    }],
  })
  assert.equal(content.subarray(0, 2).toString(), 'PK')
  assert.ok(content.length > 10_000)
})
