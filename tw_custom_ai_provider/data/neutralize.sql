-- Prevent copied databases from using production credentials or keyless providers.
UPDATE ai_provider
   SET api_key = NULL,
       active = FALSE,
       data_sharing_accepted = FALSE,
       connection_status = 'not_tested';
