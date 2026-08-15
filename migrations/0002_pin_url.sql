-- Store the public Pinterest URL next to the pin id after a successful
-- publish, so the queue itself has a clickable link (not only the id).
ALTER TABLE pin_queue ADD COLUMN pinterest_pin_url TEXT;

UPDATE pin_queue
SET pinterest_pin_url = 'https://www.pinterest.com/pin/' || pinterest_pin_id || '/'
WHERE pinterest_pin_id IS NOT NULL
  AND pinterest_pin_id != ''
  AND pinterest_pin_url IS NULL;
