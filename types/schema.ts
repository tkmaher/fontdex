import { Schema } from "effect";

export const FontFilter = Schema.Struct({
  searchString: Schema.optional(Schema.String),
  classification: Schema.optional(Schema.String),
  styles: Schema.Array(Schema.String),
  subsets: Schema.Array(Schema.String),
  styleOr: Schema.Boolean,
  subsetOr: Schema.Boolean,
  sortBy: Schema.String,
  page: Schema.Number,
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
});
export type FontRow = Schema.Schema.Type<typeof FontRow>;

export const FontResult = Schema.Struct ({
  data: Schema.Array(FontRow),
  rows: Schema.Number,
  pages: Schema.Number,
});