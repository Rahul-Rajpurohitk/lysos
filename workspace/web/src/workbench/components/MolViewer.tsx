// 3Dmol.js-based 3D viewer for molecules + protein-ligand poses (light theme)

import { useEffect, useRef } from 'react'

interface MolViewerProps {
  smiles?: string
  pdbId?: string
  className?: string
}

declare global {
  interface Window {
    $3Dmol?: any
  }
}

export function MolViewer({ smiles, pdbId, className }: MolViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)

  useEffect(() => {
    let cancelled = false

    async function ensure3Dmol() {
      if (window.$3Dmol) return
      await new Promise<void>((resolve, reject) => {
        const script = document.createElement('script')
        script.src = 'https://3Dmol.org/build/3Dmol-min.js'
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load 3Dmol'))
        document.head.appendChild(script)
      })
    }

    async function render() {
      try {
        await ensure3Dmol()
        if (cancelled || !containerRef.current || !window.$3Dmol) return

        if (!viewerRef.current) {
          viewerRef.current = window.$3Dmol.createViewer(containerRef.current, {
            backgroundColor: '#f8fafc',  // slate-50, light theme
          })
        }

        const viewer = viewerRef.current
        viewer.removeAllModels()
        viewer.removeAllShapes()
        viewer.removeAllSurfaces()

        if (pdbId) {
          const pdb = await fetch(`https://files.rcsb.org/download/${pdbId}.pdb`)
            .then((r) => r.text())
          viewer.addModel(pdb, 'pdb')
          viewer.setStyle({}, { cartoon: { color: 'spectrum' } })
          viewer.addSurface(window.$3Dmol.SurfaceType.VDW, {
            opacity: 0.3,
            color: '#94a3b8',  // slate-400
          })
        }

        if (smiles) {
          const sdfRes = await fetch(
            `https://cactus.nci.nih.gov/chemical/structure/${encodeURIComponent(smiles)}/sdf`
          )
          if (sdfRes.ok) {
            const sdf = await sdfRes.text()
            viewer.addModel(sdf, 'sdf')
            viewer.setStyle({ model: -1 }, { stick: { colorscheme: 'greenCarbon' } })
          }
        }

        viewer.zoomTo()
        viewer.render()
      } catch (err) {
        console.error('MolViewer render error', err)
      }
    }

    render()
    return () => {
      cancelled = true
    }
  }, [smiles, pdbId])

  return (
    <div
      ref={containerRef}
      className={className ?? 'w-full h-full min-h-[300px] relative'}
      style={{ background: '#f8fafc' }}
    />
  )
}
