package com.vinsguru.gateway.service;

import com.vinsguru.gateway.client.MovieClient;
import com.vinsguru.gateway.client.SearchClient;
import com.vinsguru.gateway.client.UserClient;
import com.vinsguru.gateway.dto.HomePageDto;
import org.springframework.stereotype.Service;

@Service
public class GatewayService {

    private static final int FEATURED_MOVIE_ID = 1;
    private static final String TRENDING_QUERY = "the";

    private final MovieClient movieClient;
    private final UserClient userClient;
    private final SearchClient searchClient;

    public GatewayService(MovieClient movieClient, UserClient userClient, SearchClient searchClient) {
        this.movieClient = movieClient;
        this.userClient = userClient;
        this.searchClient = searchClient;
    }

    /**
     * Build a home page for a user by fanning out to the mesh: the user's profile
     * and recommendations (user-service, which itself calls auth + recommendation),
     * a trending list (search-service -> catalog), and a featured movie
     * (movie-service -> actor + review).
     */
    public HomePageDto browse(Integer userId) {
        var user = this.userClient.getUser(userId);
        var trending = this.searchClient.search(TRENDING_QUERY);
        var featured = this.movieClient.getMovie(FEATURED_MOVIE_ID);
        return new HomePageDto(userId, user, trending, featured);
    }

}
