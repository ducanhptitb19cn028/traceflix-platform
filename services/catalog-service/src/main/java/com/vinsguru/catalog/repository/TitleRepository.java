package com.vinsguru.catalog.repository;

import com.vinsguru.catalog.entity.Title;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface TitleRepository extends JpaRepository<Title, Integer> {

    List<Title> findByNameContainingIgnoreCaseOrGenreContainingIgnoreCase(String name, String genre);

}
