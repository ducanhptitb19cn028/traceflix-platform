package com.vinsguru.user.service;

import com.vinsguru.user.client.AuthClient;
import com.vinsguru.user.client.RecommendationClient;
import com.vinsguru.user.dto.AccountDto;
import com.vinsguru.user.dto.UserDto;
import com.vinsguru.user.entity.Profile;
import com.vinsguru.user.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class UserService {

    private final ProfileRepository repository;
    private final AuthClient authClient;
    private final RecommendationClient recommendationClient;

    public UserService(ProfileRepository repository,
                       AuthClient authClient,
                       RecommendationClient recommendationClient) {
        this.repository = repository;
        this.authClient = authClient;
        this.recommendationClient = recommendationClient;
    }

    public Optional<UserDto> getUser(Integer id) {
        return this.repository.findById(id).map(this::enrich);
    }

    private UserDto enrich(Profile p) {
        // role from auth-service, personalised titles from recommendation-service
        AccountDto account = this.authClient.getAccount(p.getId());
        var recommendations = this.recommendationClient.getRecommendations(p.getId());
        var role = account == null ? "UNKNOWN" : account.role();
        return new UserDto(p.getId(), p.getName(), p.getEmail(), p.getTier(),
                role, recommendations);
    }

}
