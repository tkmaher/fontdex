'use client';

import { useEffect, useRef } from 'react';
import cytoscape, {
  Core,
  EdgeDefinition,
  ElementDefinition,
  NodeDefinition,
} from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import { Effect, pipe } from 'effect';
import {
  FontResult,
  FontRow,
  SiteResult,
  SiteRow,
} from '@/types/schema';
import { TagType } from '@/components/display/sitefontinspector';
import { BubbleSortType } from '../filters/fontsearch-form';

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
  '#b97abc',
];

function colorForIndex(i: number): string {
  return PALETTE[i % PALETTE.length];
}

type GraphResult =
  SiteResult
  | FontResult;

type GraphItem = {
  label: string;
  count: number;
  row?: FontRow | SiteRow;
};

function getGraphItems(fontdata: GraphResult): GraphItem[] {
  switch (fontdata._tag) {
    case 'BubbleFontResult':
    case 'BubbleSiteResult':
      return fontdata.data.map((n) => ({
        label: `${n.label} (${n.count})`,
        count: n.count,
      }));

    case 'RowFontResult':
      return fontdata.data.map((n) => ({
        label: n.font,
        count: 1,
        row: n
      }));

    case 'RowSiteResult':
      return fontdata.data.map((n) => ({
        label: n.domain,
        count: 1,
        row: n
      }));
  }
}


function buildElements(
  fontdata: GraphResult,
) {
  return Effect.sync(() => {
    const items = getGraphItems(fontdata);

    const nodes: ElementDefinition[] = items.map((n, i) => ({
      data: {
        id: `bubble-${i}-${n.label}`,
        label: n.label,
        count: n.count,
        color: colorForIndex(i),
        row: n.row ?? null
      },
      classes: 'hidden',
    }));

    return {
      nodes: nodes as NodeDefinition[],
      edges: [] as EdgeDefinition[],
    };
  });
}

function fadeInAfterPaint(
  cy: Core,
  nodes: cytoscape.NodeCollection,
) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      nodes.removeClass('hidden');
    });
  });
}

export default function CytoscapeGraph({
  fontdata,
  filter,
  tagCallback,
  catCallback,
  setter
}: {
  fontdata: GraphResult;
  filter: BubbleSortType;
  tagCallback: (
    data: TagType,
    clearBefore: boolean,
  ) => void;
  catCallback: (
    category: string,
    clearBefore: boolean,
  ) => void;
  setter: (row: FontRow | SiteRow) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  /*
   * Create the Cytoscape instance.
   */
  useEffect(() => {
    if (!containerRef.current) return;

    const items = getGraphItems(fontdata);

    const counts = items.map((n) => n.count);
    const minCount = counts.length
      ? Math.min(...counts)
      : 0;
    const maxCount = counts.length
      ? Math.max(...counts)
      : 1;

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
              'transition-property':
                'opacity, background-opacity',
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
      })),
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

        /*
         * Clicking a font calls tagCallback.
         * Clicking a site calls catCallback.
         */
        cy.on('tap', 'node', (evt) => {
          const node = evt.target;
          const name = node.data('label').split(' (')[0] as string | undefined;

          if (!name) return;

          const row = node.data('row') as FontRow | SiteRow | null;
          if (row) {
            setter(row);
            return;
          }

          if (
            fontdata._tag === 'BubbleFontResult' ||
            fontdata._tag === 'RowFontResult'
          ) {
            tagCallback(
              {
                label: name,
                type: filter,
              } as TagType,
              false,
            );
          } else {
            catCallback(
              name,
              false,
            );
          }
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
  }, [
    fontdata,
    filter,
    tagCallback,
    catCallback,
  ]);

  /*
   * Update elements + re-layout whenever the list changes.
   *
   * This keeps the existing Cytoscape instance when possible,
   * while preserving the original sizing/layout behavior.
   */
  useEffect(() => {
    const cy = cyRef.current;

    if (!cy) return;

    const items = getGraphItems(fontdata);

    const counts = items.map((n) => n.count);
    const minCount = counts.length
      ? Math.min(...counts)
      : 0;
    const maxCount = counts.length
      ? Math.max(...counts)
      : 1;

    Effect.runPromise(buildElements(fontdata))
      .then(({ nodes }) => {
        cy.startBatch();

        cy.elements().remove();
        cy.add(nodes);

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
          cy.fit(undefined, 30);
          fadeInAfterPaint(cy, cy.nodes());
        });

        layout.run();
      })
      .catch(console.error);
  }, [fontdata]);

  return (
    <div
      ref={containerRef}
      className="graph-container"
    />
  );
}
