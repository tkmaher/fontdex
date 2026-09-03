import { Schema } from "effect";

export const FontFilter = Schema.Struct({
  searchString: Schema.optional(Schema.String),
  classification: Schema.optional(Schema.String),
  styles: Schema.optional(Schema.Array(Schema.String)),
  subsets: Schema.optional(Schema.Array(Schema.String)),
  styleOr: Schema.optional(Schema.Boolean),
  subsetOr: Schema.optional(Schema.Boolean),
  sortBy: Schema.optional(Schema.String),
  page: Schema.Number,
  bubbleSort: Schema.optional(Schema.String),
  searchField: Schema.optional(Schema.String),
});
export type FontFilter = Schema.Schema.Type<typeof FontFilter>;

export const FontRow = Schema.Struct({
  font: Schema.String,
  classification: Schema.String,
  style_tags: Schema.NullOr(Schema.String),
  source: Schema.String,
  subsets: Schema.NullOr(Schema.String),
  notes: Schema.NullOr(Schema.String),
  confidence: Schema.NullOr(Schema.String),
  hits: Schema.Number,
  _tag: Schema.Literal("FontRow")
});
export type FontRow = Schema.Schema.Type<typeof FontRow>;

export const RowFontResult = Schema.Struct ({
  data: Schema.Array(FontRow),
  rows: Schema.Number,
  pages: Schema.Number,
  _tag: Schema.Literal("RowFontResult"),
});

export const NodeData = Schema.Struct({
  label: Schema.String,
  count: Schema.Number,
});

export const BubbleFontResult = Schema.Struct ({
  data: Schema.Array(NodeData),
  _tag: Schema.Literal("BubbleFontResult"),

});
export type BubbleFontResult = Schema.Schema.Type<typeof BubbleFontResult>;

export const FontResult = Schema.Union(RowFontResult, BubbleFontResult);
export type FontResult = Schema.Schema.Type<typeof FontResult>;

export const SiteFilter = Schema.Struct({
  font: Schema.optional(Schema.String),
  page: Schema.Number,
  category: Schema.optional(Schema.String),
  searchString: Schema.optional(Schema.String),
  sortBy: Schema.optional(Schema.String),
  bubbleSort: Schema.optional(Schema.String),
});
export type SiteFilter = Schema.Schema.Type<typeof SiteFilter>;

export const SiteRow = Schema.Struct({
  domain: Schema.String,
  category: Schema.String,
  font1: Schema.NullOr(Schema.String),
  font2: Schema.NullOr(Schema.String),
  font3: Schema.NullOr(Schema.String),
  rank: Schema.Number,
  _tag: Schema.Literal("SiteRow")
});
export type SiteRow = Schema.Schema.Type<typeof SiteRow>;

export const RowSiteResult = Schema.Struct({
  data: Schema.Array(SiteRow),
  rows: Schema.Number,
  pages: Schema.Number,
  _tag: Schema.Literal("RowSiteResult")
});

export const BubbleSiteResult = Schema.Struct({
  data: Schema.Array(NodeData),
  _tag: Schema.Literal("BubbleSiteResult"),
});

export const SiteResult = Schema.Union(BubbleSiteResult, RowSiteResult);
