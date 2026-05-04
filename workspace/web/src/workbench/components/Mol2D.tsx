// Lightweight 2D structure depiction via RDKit-JS — draws to canvas
// (avoids any HTML injection — uses RDKit's draw_to_canvas API).

import { useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    initRDKitModule?: () => Promise<any>
    RDKit?: any
  }
}

let rdkitPromise: Promise<any> | null = null

async function getRDKit() {
  if (window.RDKit) return window.RDKit
  if (!rdkitPromise) {
    rdkitPromise = new Promise(async (resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://unpkg.com/@rdkit/rdkit/dist/RDKit_minimal.js'
      script.onload = async () => {
        if (window.initRDKitModule) {
          window.RDKit = await window.initRDKitModule()
          resolve(window.RDKit)
        } else {
          reject(new Error('initRDKitModule missing'))
        }
      }
      script.onerror = () => reject(new Error('Failed to load RDKit-JS'))
      document.head.appendChild(script)
    })
  }
  return rdkitPromise
}

interface Mol2DProps {
  smiles: string
  width?: number
  height?: number
  className?: string
}

export function Mol2D({ smiles, width = 200, height = 150, className }: Mol2DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function draw() {
      try {
        const rdkit = await getRDKit()
        if (cancelled || !canvasRef.current) return

        const mol = rdkit.get_mol(smiles)
        if (!mol) {
          setError('parse failed')
          return
        }

        // Draw onto the canvas — no SVG / innerHTML
        mol.draw_to_canvas(canvasRef.current, width, height)
        mol.delete()
        setError(null)
      } catch (err) {
        setError(String(err))
      }
    }

    draw()
    return () => {
      cancelled = true
    }
  }, [smiles, width, height])

  if (error) {
    return (
      <div className={className} style={{ width, height }}>
        <span className="text-red-500 text-xs">{error}</span>
      </div>
    )
  }

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className={className}
    />
  )
}
