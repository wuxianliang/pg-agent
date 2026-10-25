ALTER TABLE v24_cordis.scopes ADD FOREIGN KEY(parent_id) REFERENCES v24_cordis.scopes(id);
ALTER TABLE v24_cordis.installs
  ADD FOREIGN KEY(scope_id) REFERENCES v24_cordis.scopes(id),
  ADD FOREIGN KEY(owner_fiber_id,owner_episode_id) REFERENCES v24_cordis.episodes(fiber_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24_cordis.fibers
  ADD FOREIGN KEY(install_id) REFERENCES v24_cordis.installs(id),
  ADD FOREIGN KEY(scope_id) REFERENCES v24_cordis.scopes(id),
  ADD FOREIGN KEY(owner_id) REFERENCES v24_cordis.fibers(id),
  ADD FOREIGN KEY(owner_id,owner_episode_id) REFERENCES v24_cordis.episodes(fiber_id,id) DEFERRABLE INITIALLY DEFERRED,
  ADD FOREIGN KEY(id,current_episode_id) REFERENCES v24_cordis.episodes(fiber_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24_cordis.episodes ADD FOREIGN KEY(fiber_id) REFERENCES v24_cordis.fibers(id);
ALTER TABLE v24_cordis.contributions
  ADD FOREIGN KEY(fiber_id,episode_id) REFERENCES v24_cordis.episodes(fiber_id,id),
  ADD FOREIGN KEY(prev_contribution_id) REFERENCES v24_cordis.contributions(id);
ALTER TABLE v24_cordis.pins
  ADD FOREIGN KEY(consumer_fiber_id,consumer_episode_id) REFERENCES v24_cordis.episodes(fiber_id,id),
  ADD FOREIGN KEY(consumer_run_id) REFERENCES v24_cordis.runs(id),
  ADD FOREIGN KEY(contribution_id) REFERENCES v24_cordis.contributions(id);
ALTER TABLE v24_cordis.runs
  ADD FOREIGN KEY(owner_fiber_id,owner_episode_id) REFERENCES v24_cordis.episodes(fiber_id,id),
  ADD FOREIGN KEY(scope_id) REFERENCES v24_cordis.scopes(id),
  ADD FOREIGN KEY(parent_run_id) REFERENCES v24_cordis.runs(id);
ALTER TABLE v24_cordis.effects
  ADD FOREIGN KEY(parent_id) REFERENCES v24_cordis.effects(id),
  ADD FOREIGN KEY(fiber_id) REFERENCES v24_cordis.fibers(id),
  ADD FOREIGN KEY(fiber_id,episode_id) REFERENCES v24_cordis.episodes(fiber_id,id),
  ADD FOREIGN KEY(run_id) REFERENCES v24_cordis.runs(id);
ALTER TABLE v24_cordis.requests ADD FOREIGN KEY(effect_id) REFERENCES v24_cordis.effects(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v24_cordis.events ADD FOREIGN KEY(effect_id) REFERENCES v24_cordis.effects(id) DEFERRABLE INITIALLY DEFERRED;
