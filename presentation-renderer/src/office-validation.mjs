import { execFile } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'

const execute = promisify(execFile)

// Prove LibreOffice can open and export a deck without retaining user content.
export const validateWithLibreOffice = async content => {
  const directory = await mkdtemp(join(tmpdir(), 'anios-presentation-'))
  const inputPath = join(directory, 'presentation.pptx')
  const outputPath = join(directory, 'presentation.pdf')
  try {
    await writeFile(inputPath, content)
    await execute(
      'soffice',
      [
        '--headless',
        '--convert-to',
        'pdf',
        '--outdir',
        directory,
        inputPath,
      ],
      {
        timeout: 45_000,
        maxBuffer: 1_000_000,
      },
    )
    const pdf = await readFile(outputPath)
    if (!pdf.subarray(0, 5).equals(Buffer.from('%PDF-'))) {
      throw new Error('LibreOffice did not emit a PDF package')
    }
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
}
