-- DreamJar — Supabase Storage Setup for Jar Photos (CMPA-912)
-- Run this in Supabase SQL Editor to create the storage bucket and policies.

-- Create public bucket for jar images
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('jar-images', 'jar-images', true, 5242880, ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
ON CONFLICT (id) DO NOTHING;

-- Allow anyone to upload (matches existing permissive RLS model)
CREATE POLICY "allow_upload" ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'jar-images');

-- Allow anyone to read
CREATE POLICY "allow_read" ON storage.objects FOR SELECT
  USING (bucket_id = 'jar-images');

-- Allow anyone to update/delete their uploads
CREATE POLICY "allow_update" ON storage.objects FOR UPDATE
  USING (bucket_id = 'jar-images');
CREATE POLICY "allow_delete" ON storage.objects FOR DELETE
  USING (bucket_id = 'jar-images');
