package com.vinsguru.recommendation.service;

import com.vinsguru.recommendation.client.CatalogClient;
import com.vinsguru.recommendation.dto.TitleDto;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.List;

@Service
public class RecommendationService {

    private static final int TOP_N = 5;

    private final CatalogClient catalogClient;

    public RecommendationService(CatalogClient catalogClient) {
        this.catalogClient = catalogClient;
    }

    /**
     * Simple, deterministic recommender: pull the catalog, rotate the ranking by the
     * user id so different users see a different ordering, then return the top-rated
     * titles. (Stand-in for a real model -- the point is the catalog dependency.)
     */
    public List<TitleDto> recommend(Integer userId) {
        var titles = this.catalogClient.getAllTitles();
        long seed = userId == null ? 0 : userId;
        return titles.stream()
                     .sorted(Comparator
                             .comparingDouble((TitleDto t) -> personalisedScore(t, seed))
                             .reversed())
                     .limit(TOP_N)
                     .toList();
    }

    private static double personalisedScore(TitleDto t, long seed) {
        double base = t.rating() == null ? 0.0 : t.rating();
        // small per-user perturbation so recommendations differ by user
        double bias = ((t.id() + seed) % 3) * 0.15;
        return base + bias;
    }

}
