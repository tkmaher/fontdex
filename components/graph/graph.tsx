'use client';

import { useEffect, useRef } from 'react';
import cytoscape, { Core, EdgeDefinition, ElementDefinition, NodeDefinition } from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import { Effect, pipe } from 'effect';
import { BubbleFontResult } from '@/types/schema';

// Register the layout extension once per module load.
if (typeof cytoscape('layout', 'cose-bilkent') === 'undefined') {
  cytoscape.use(coseBilkent);
}

// A palette to cycle through so each bubble gets a distinct color.
const PALETTE = [
  '#D2D7DF',
  '#BDBBB0',
  '#F7CB15',
  '#F55D3E',
  '#8A897C',
  '#F7F7F7',
  '#9EE37D',
  '#FF5154',
  '#b97abc'
];

function colorForIndex(i: number): string {
  return PALETTE[i % PALETTE.length];
}

const buildElements = (fontdata: BubbleFontResult) =>
  Effect.sync(() => {
    const nodes: ElementDefinition[] = fontdata.data.map((n, i) => ({
      data: {
        id: `bubble-${i}-${n.label}`,
        label: `${n.label} (${n.count})`,
        count: n.count,
        color: colorForIndex(i),
      },
      classes: 'hidden',
    }));

    return { nodes: nodes as NodeDefinition[], edges: [] as EdgeDefinition[] };
  });

function fadeInAfterPaint(cy: Core, nodes: cytoscape.NodeCollection) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      nodes.removeClass('hidden');
    });
  });
}

interface CytoscapeGraphProps {
  fontdata: BubbleFontResult;
}

export default function CytoscapeGraph({ fontdata }: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  // Create the cytoscape instance once.
  useEffect(() => {
    if (!containerRef.current) return;

    const counts = fontdata.data.map((n) => n.count);
    const minCount = counts.length ? Math.min(...counts) : 0;
    const maxCount = counts.length ? Math.max(...counts) : 1;

    const program = pipe(
      buildElements(fontdata),
      Effect.map((elements) => ({
        container: containerRef.current!,
        boxSelectionEnabled: false,
        elements,
        style: [
          {
            selector: 'node',
            style: {
              'background-color': 'data(color)',
              label: 'data(label)',
              'text-valign': 'center',
              'text-halign': 'center' as 'center',
              color: '#171717',
              'font-size': `mapData(count, ${minCount}, ${maxCount}, 5, 30)`,
              width: `mapData(count, ${minCount}, ${maxCount}, 1, 500)`,
              height: `mapData(count, ${minCount}, ${maxCount}, 1, 500)`,
              'overlay-opacity': 0,
              'transition-property': 'opacity, background-opacity',
              'transition-duration': '0.1s',
              'font-family': 'CommitMono, monospace',
            },
          },
          {
            // Entrance state only - fully independent of hover.
            selector: 'node.hidden',
            style: {
              opacity: 0,
            },
          },
          {
            // Hover state only - fully independent of the entrance fade.
            selector: 'node.hover',
            style: {
              'background-opacity': 0.5,
              'cursor': 'pointer',
            },
          },
        ],
        layout: {
          name: 'cose-bilkent',
          fit: true,
          padding: 30,
          randomize: true,
          nodeRepulsion: 8000,
          idealEdgeLength: 100,
          // Instant positioning - the "entrance" is opacity-only.
          animate: false,
        } as any,
      }))
    );

    let cancelled = false;

    Effect.runPromise(program)
      .then((config) => {
        if (cancelled) return;

        const cy = cytoscape(config);
        cyRef.current = cy;

        cy.on('mouseover', 'node', (evt) => {
          evt.target.addClass('hover');
        });
        cy.on('mouseout', 'node', (evt) => {
          evt.target.removeClass('hover');
        });


        // Empty effect - fill in whatever should happen on node click.
        cy.on('tap', 'node', (evt) => {
          const node = evt.target;
          console.log('here');
        });

        cy.ready(() => {
          fadeInAfterPaint(cy, cy.nodes());
        });
      })
      .catch(console.error);

    return () => {
      cancelled = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
    // Only (re)create the cytoscape instance on mount/unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update elements + re-layout whenever the list changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const counts = fontdata.data.map((n) => n.count);
    const minCount = counts.length ? Math.min(...counts) : 0;
    const maxCount = counts.length ? Math.max(...counts) : 1;

    Effect.runPromise(buildElements(fontdata))
      .then(({ nodes }) => {
        cy.startBatch();
        cy.elements().remove();
        cy.add(nodes); // added with the "hidden" class already applied
        cy.style()
          .selector('node')
          .style({
            width: `mapData(count, ${minCount}, ${maxCount}, 30, 150)`,
            height: `mapData(count, ${minCount}, ${maxCount}, 30, 150)`,
          })
          .update();
        cy.endBatch();

        const layout = cy.layout({
          name: 'cose-bilkent',
          fit: true,
          padding: 30,
          randomize: true,
          animate: false,
        } as any);

        layout.one('layoutstop', () => {
          cy.fit(undefined, 30); // ensure full graph is in view
          fadeInAfterPaint(cy, cy.nodes());
        });

        layout.run();
      })
      .catch(console.error);
  }, [fontdata]);

  return (
    <div
      ref={containerRef}
      className='graph-container'
    />
  );
}